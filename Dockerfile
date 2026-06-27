# Image unique "tout-en-un" : l'API sert aussi le frontend builde (cf.
# nfogen/api.py, NFOGEN_FRONTEND_DIST) -- pas de nginx, pas de
# docker-compose, un seul conteneur a lancer pour avoir l'app complete.

FROM node:22-slim AS frontend-build
WORKDIR /app/frontend
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

FROM python:3.12-slim

# libmediainfo0v5 : dependance systeme requise par pymediainfo pour
# l'extraction video/audio (cf. README.md, section Installation).
RUN apt-get update \
    && apt-get install -y --no-install-recommends libmediainfo0v5 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY pyproject.toml README.md ./
COPY nfogen ./nfogen
RUN pip install --no-cache-dir ".[api]"

COPY --from=frontend-build /app/frontend/dist ./frontend_dist
ENV NFOGEN_FRONTEND_DIST=/app/frontend_dist

EXPOSE 8000
CMD ["uvicorn", "nfogen.api:app", "--host", "0.0.0.0", "--port", "8000"]
