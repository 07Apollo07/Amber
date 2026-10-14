#!/usr/bin/env bash
# Amber on Cloud Run (free-tier settings). Usage: deploy/cloudrun.sh setup | secrets | deploy
# Run from anywhere; reads deploy/cloudrun.env. Nothing here runs until you call it.
set -euo pipefail
cd "$(dirname "$0")/.."
source deploy/cloudrun.env

: "${PROJECT_ID:?}" "${REGION:?}" "${SQL_INSTANCE:?}" "${GOOGLE_OAUTH_CLIENT_ID:?}" "${FIREBASE_PROJECT_ID:?}"
PROJECT_NUMBER=$(gcloud projects describe "$PROJECT_ID" --format='value(projectNumber)')
REPO="$REGION-docker.pkg.dev/$PROJECT_ID/amber"
API_SA="amber-api@$PROJECT_ID.iam.gserviceaccount.com"
WEB_SA="amber-web@$PROJECT_ID.iam.gserviceaccount.com"
# Cloud Run URLs are predictable, so each service can be told the other's address before it exists.
WEB_URL="https://amber-web-$PROJECT_NUMBER.$REGION.run.app"
API_URL="https://amber-api-$PROJECT_NUMBER.$REGION.run.app"
KMS_KEY="projects/$PROJECT_ID/locations/$REGION/keyRings/amber/cryptoKeys/oauth-tokens"
SECRETS=(amber-oauth-client-secret amber-firebase-web-api-key amber-gemini-api-key amber-state-cookie-key amber-database-dsn amber-litellm-api-key)

setup() {  # one time
  gcloud services enable run.googleapis.com cloudbuild.googleapis.com artifactregistry.googleapis.com \
    secretmanager.googleapis.com cloudkms.googleapis.com sqladmin.googleapis.com drive.googleapis.com \
    generativelanguage.googleapis.com identitytoolkit.googleapis.com --project "$PROJECT_ID"
  gcloud artifacts repositories describe amber --location "$REGION" >/dev/null 2>&1 ||
    gcloud artifacts repositories create amber --repository-format docker --location "$REGION"
  for sa in amber-api amber-web; do
    gcloud iam service-accounts describe "$sa@$PROJECT_ID.iam.gserviceaccount.com" >/dev/null 2>&1 ||
      gcloud iam service-accounts create "$sa"
  done
  gcloud projects add-iam-policy-binding "$PROJECT_ID" --member "serviceAccount:$API_SA" --role roles/cloudsql.client >/dev/null
  gcloud projects add-iam-policy-binding "$PROJECT_ID" --member "serviceAccount:$API_SA" --role roles/firebaseauth.admin >/dev/null
  gcloud kms keyrings describe amber --location "$REGION" >/dev/null 2>&1 || gcloud kms keyrings create amber --location "$REGION"
  gcloud kms keys describe oauth-tokens --keyring amber --location "$REGION" >/dev/null 2>&1 ||
    gcloud kms keys create oauth-tokens --keyring amber --location "$REGION" --purpose encryption
  gcloud kms keys add-iam-policy-binding oauth-tokens --keyring amber --location "$REGION" \
    --member "serviceAccount:$API_SA" --role roles/cloudkms.cryptoKeyEncrypterDecrypter >/dev/null
  for s in "${SECRETS[@]}"; do
    gcloud secrets describe "$s" >/dev/null 2>&1 || gcloud secrets create "$s" --replication-policy automatic
    gcloud secrets add-iam-policy-binding "$s" --member "serviceAccount:$API_SA" --role roles/secretmanager.secretAccessor >/dev/null
  done
  echo "Next: add the secret values (deploy/cloudrun.sh secrets), then register $WEB_URL/api/auth/google/callback"
  echo "as an authorized redirect URI (and $WEB_URL as an origin) on the OAuth client."
}

secrets() {  # prompts for each value; nothing is echoed or written to disk
  for s in "${SECRETS[@]}"; do
    case "$s" in
      amber-state-cookie-key) echo "$s: generating a new Fernet key"
        python3 -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode(), end='')" | gcloud secrets versions add "$s" --data-file=- ;;
      amber-database-dsn) echo "Format: postgresql://amber_app:<password>@/<dbname>?host=/cloudsql/$PROJECT_ID:$REGION:$SQL_INSTANCE"
        read -rsp "$s: " v; echo; printf %s "$v" | gcloud secrets versions add "$s" --data-file=- ;;
      *) read -rsp "$s: " v; echo; printf %s "$v" | gcloud secrets versions add "$s" --data-file=- ;;
    esac
  done
}

deploy() {
  for s in "${SECRETS[@]}"; do  # fail now, not after the builds
    [[ -n $(gcloud secrets versions list "$s" --filter='state=ENABLED' --limit=1 --format='value(name)') ]] ||
      { echo "Secret $s has no value yet. Run: deploy/cloudrun.sh secrets" >&2; exit 1; }
  done
  local tag; tag=$(git rev-parse --short HEAD)
  gcloud builds submit api --tag "$REPO/api:$tag"
  gcloud builds submit ui --config ui/cloudbuild.yaml --substitutions "_IMAGE=$REPO/web:$tag,_API_ORIGIN=$API_URL"

  local envfile; envfile=$(mktemp); trap 'rm -f "$envfile"' EXIT
  cat > "$envfile" <<YAML
AMBER_ENV: prod
AMBER_PUBLIC_BASE_URL: "$WEB_URL"
AMBER_COOKIE_SECURE: "true"
AMBER_GOOGLE_OAUTH_CLIENT_ID: "$GOOGLE_OAUTH_CLIENT_ID"
AMBER_FIREBASE_PROJECT_ID: "$FIREBASE_PROJECT_ID"
AMBER_TOKEN_KMS_KEY: "$KMS_KEY"
AMBER_BOOTSTRAP_ADMIN_EMAILS: "${BOOTSTRAP_ADMIN_EMAILS:-}"
AMBER_PICKER_API_KEY: "${PICKER_API_KEY:-}"
AMBER_GOOGLE_CLOUD_PROJECT_NUMBER: "$PROJECT_NUMBER"
AMBER_AGENT_MODEL_NAME: "${AGENT_MODEL_NAME:-gemini-2.5-flash}"
AMBER_LITELLM_BASE_URL: "${LITELLM_BASE_URL:-}"
YAML
  gcloud run deploy amber-api --image "$REPO/api:$tag" --region "$REGION" --service-account "$API_SA" \
    --allow-unauthenticated --ingress all --add-cloudsql-instances "$PROJECT_ID:$REGION:$SQL_INSTANCE" \
    --memory 1Gi --cpu 1 --timeout 300 --concurrency 10 --min-instances 0 --max-instances 3 --port 8000 \
    --env-vars-file "$envfile" \
    --set-secrets "AMBER_GOOGLE_OAUTH_CLIENT_SECRET=amber-oauth-client-secret:latest,AMBER_FIREBASE_WEB_API_KEY=amber-firebase-web-api-key:latest,AMBER_GEMINI_API_KEY=amber-gemini-api-key:latest,AMBER_STATE_COOKIE_KEY=amber-state-cookie-key:latest,AMBER_DATABASE_DSN=amber-database-dsn:latest,AMBER_LITELLM_API_KEY=amber-litellm-api-key:latest"
  gcloud run deploy amber-web --image "$REPO/web:$tag" --region "$REGION" --service-account "$WEB_SA" \
    --allow-unauthenticated --memory 512Mi --min-instances 0 --max-instances 3 --port 3000 \
    --set-env-vars "AMBER_API_ORIGIN=$API_URL"
  echo "Open $WEB_URL"
}

"${1:?usage: $0 setup|secrets|deploy}"