# syntax=docker/dockerfile:1

# Debian slim has glibc, which LiveKit Cloud requires. Do not set LiveKit secrets here.
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1
ENV PYTHONDONTWRITEBYTECODE=1
ENV PIP_DISABLE_PIP_VERSION_CHECK=1
ENV HOME=/app

# gcc is only needed if a package has no wheel. libgomp1 is needed by onnxruntime.
RUN apt-get update && apt-get install -y --no-install-recommends \
        gcc \
        g++ \
        python3-dev \
        libgomp1 \
    && rm -rf /var/lib/apt/lists/*

# Same direct packages as pyproject.toml, pinned to the local .venv versions.
RUN pip install --no-cache-dir \
        "livekit-agents==1.8.13" \
        "livekit-api==1.2.3" \
        "livekit-plugins-deepgram==1.8.13" \
        "livekit-plugins-groq==1.8.13" \
        "livekit-plugins-cartesia==1.8.13" \
        "livekit-plugins-silero==1.8.13" \
        "livekit-plugins-turn-detector==1.8.13" \
        "fastapi==0.165.0" \
        "uvicorn==0.54.0" \
        "httpx==0.28.1" \
        "python-dotenv==1.2.4" \
        "pydantic==2.14.4"

ARG UID=10001
RUN adduser \
        --disabled-password \
        --gecos "" \
        --home "/app" \
        --shell "/sbin/nologin" \
        --uid "${UID}" \
        appuser

WORKDIR /app

COPY --chown=appuser:appuser pyproject.toml ./
COPY --chown=appuser:appuser agent ./agent

USER appuser

# Download plugin model files while building, so the first call does not have to.
RUN python -m livekit.agents download-files

CMD ["python", "agent/main.py", "start"]
