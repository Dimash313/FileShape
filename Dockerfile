FROM python:3.12-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    TMPDIR=/tmp

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends ffmpeg ca-certificates \
    && rm -rf /var/lib/apt/lists/* \
    && groupadd --system fileshape \
    && useradd --system --gid fileshape --home-dir /app fileshape

COPY requirements.txt ./
RUN python -m pip install --no-cache-dir -r requirements.txt

COPY --chown=fileshape:fileshape main.py config.py ./
COPY --chown=fileshape:fileshape services ./services

USER fileshape
CMD ["python", "main.py"]
