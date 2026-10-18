FROM python:3.12-slim
COPY --from=ghcr.io/astral-sh/uv:0.5 /uv /usr/local/bin/uv
WORKDIR /app
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy PYTHONUNBUFFERED=1
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project
COPY main.py ./
COPY amber ./amber
RUN useradd --system --uid 10001 amber && chown -R amber /app
USER amber
ENV PATH="/app/.venv/bin:$PATH" AMBER_HOST=0.0.0.0 AMBER_PORT=8000
EXPOSE 8000
CMD ["python", "main.py"]
