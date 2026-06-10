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
    RUN pip install --no-cache-dir -r requirements.txt
    COPY backend/ ./
    COPY --from=frontend /frontend/dist ./static
    EXPOSE 8000
    CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]