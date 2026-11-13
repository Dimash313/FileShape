FROM python:3.12-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    TMPDIR=/tmp

WORKDIR /app
COPY requirements.txt ./

# Keep the runtime installation in one layer (also avoids repeated full-tree
# copies on VFS development daemons). No development data enters the image.
RUN apt-get update \
    && apt-get install -y --no-install-recommends ffmpeg ca-certificates \
    && rm -rf /var/lib/apt/lists/* \
    && python -m pip install --no-cache-dir -r requirements.txt \
    && groupadd --system fileshape \
    && useradd --system --gid fileshape --home-dir /app fileshape \
    && mkdir -m 0700 /app/state \
    && chown fileshape:fileshape /app/state

# .dockerignore explicitly permits only runtime sources.
COPY --chown=fileshape:fileshape . ./

USER fileshape
CMD ["python", "main.py"]
