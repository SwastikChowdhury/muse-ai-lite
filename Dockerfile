# ---- Stage 1: build the React frontend ----
    FROM node:20-alpine AS frontend
    WORKDIR /frontend
    COPY frontend/package*.json ./
    RUN npm ci
    COPY frontend/ ./
    RUN npm run build
    
    # ---- Stage 2: backend + built frontend ----
    FROM python:3.10-slim AS app
    WORKDIR /app
    COPY backend/requirements.txt ./
    # CPU-only torch (the default Linux wheel bundles multi-GB CUDA deps this
    # image can't use) + a BuildKit pip cache so rebuilds reuse downloaded wheels
    # instead of re-fetching the whole ML stack every time.
    RUN --mount=type=cache,target=/root/.cache/pip \
        pip install --extra-index-url https://download.pytorch.org/whl/cpu \
        -r requirements.txt
    COPY backend/ ./
    # main.py now lives in the app/ package, and it resolves the SPA build
    # relative to itself (app/static), so copy the frontend there.
    COPY --from=frontend /frontend/dist ./app/static
    EXPOSE 8000
    CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]