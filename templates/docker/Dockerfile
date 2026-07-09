FROM python:3.12-slim AS builder

WORKDIR /app

COPY pyproject.toml README.md ./
COPY src/ src/

RUN pip install --no-cache-dir build \
  && python -m build --wheel

FROM python:3.12-slim

WORKDIR /app

COPY --from=builder /app/dist/*.whl .
RUN pip install --no-cache-dir *.whl && rm *.whl

RUN adduser --disabled-password --no-create-home appuser
USER appuser

HEALTHCHECK --interval=30s --timeout=5s --start-period=5s --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/health')" || exit 1

LABEL org.opencontainers.image.title="Service"
LABEL org.opencontainers.image.description="FastAPI microservice"
LABEL org.opencontainers.image.source="https://github.com/modelink/service"
LABEL org.opencontainers.image.licenses="MIT"

EXPOSE 8000

CMD ["uvicorn", "src.main:app", "--host", "0.0.0.0", "--port", "8000"]
