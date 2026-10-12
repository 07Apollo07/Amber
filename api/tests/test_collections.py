import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from amber.api.documents import _clean_tags, build_access, split_csv

USER = {"email": "Me@Acme.com", "domain": "acme.com"}


def test_private_grants_only_the_owner():
    option, grants = build_access(USER, "private", [])
    assert option == "private"
    assert [(g["principal_type"], g["principal_value"]) for g in grants] == [("user", "me@acme.com")]


def test_people_grants_dedupe_and_skip_the_owner():
    option, grants = build_access(USER, "people", ["a@x.com", "A@x.com", "me@acme.com"])
    assert option == "specific_people"
    assert [g["principal_value"] for g in grants] == ["me@acme.com", "a@x.com"]


def test_people_rejects_bad_email():
    with pytest.raises(HTTPException) as exc:
        build_access(USER, "people", ["not-an-email"])
    assert exc.value.status_code == 400


def test_domain_needs_a_domain():
    option, grants = build_access(USER, "domain", [])
    assert option == "domain" and grants[-1] == {"principal_type": "domain", "principal_value": "acme.com", "origin": "manual"}
    with pytest.raises(HTTPException):
        build_access({"email": "me@gmail.com", "domain": None}, "domain", [])


def test_tag_and_csv_cleaning():
    assert split_csv(" a, ,b ,") == ["a", "b"]
    assert _clean_tags(["Q3 Plan", "q3-plan", ""]) == ["q3-plan"]


@pytest.mark.parametrize(
    "method,path",
    [("post", "/api/collections"), ("put", "/api/collections/00000000-0000-0000-0000-000000000000/access")],
)
def test_collection_endpoints_reject_anonymous(client: TestClient, method: str, path: str):
    response = getattr(client, method)(path, json={"name": "x", "kind": "private"})
    assert response.status_code in (401, 403)
