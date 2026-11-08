# VideoGen MKS — imagem única (1 processo uvicorn; ver docs/design/07 §5).
# trixie: FFmpeg 7.x com libass (o projeto exige FFmpeg >= 6; bookworm traz 5.1).
FROM python:3.12-slim-trixie

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    WORKSPACE_DIR=/workspace \
    MODELS_CONFIG=/app/config/models.yaml

RUN apt-get update \
    && apt-get install -y --no-install-recommends ffmpeg fonts-dejavu-core \
    && rm -rf /var/lib/apt/lists/* \
    && useradd --create-home --uid 10001 app \
    && mkdir -p /workspace && chown app:app /workspace

WORKDIR /app
COPY pyproject.toml README.md ./
COPY src ./src
COPY config ./config
RUN pip install .

USER app
VOLUME ["/workspace"]
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=10s --start-period=20s --retries=3 \
    CMD python -c "import urllib.request as u; u.urlopen('http://127.0.0.1:8000/readyz', timeout=8)"
CMD ["uvicorn", "videogen.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]
