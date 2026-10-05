FROM node:22-alpine AS frontend
WORKDIR /build
COPY src/frontend/package*.json ./
RUN npm ci
COPY src/frontend/ ./
RUN npm run build

FROM python:3.13-slim
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    GAME_VAULT_SNAPSHOT=/data/game-vault-snapshot.json \
    GAME_VAULT_COVERS=/data/covers \
    GAME_VAULT_ARTWORK=/data/artwork
WORKDIR /app
COPY config/requirements-static.txt ./requirements.txt
RUN pip install --no-cache-dir -r requirements.txt
COPY src/__init__.py ./src/__init__.py
COPY src/api/__init__.py src/api/serve.py src/api/static_main.py src/api/static_snapshot.py ./src/api/
COPY --from=frontend /build/dist/frontend/browser ./src/frontend/dist/frontend/browser
EXPOSE 4200
CMD ["python", "-m", "src.api.serve"]
