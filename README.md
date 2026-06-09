# muse-ai-lite

A companion-chat prototype: a streaming, multi-agent companion that remembers
you across sessions.

## Stack
- Frontend: React + Vite (built to static, served by FastAPI)
- Backend: FastAPI + Uvicorn, WebSocket streaming
- LLM: Gemini 2.5 Flash
- Persistence: MongoDB Atlas
- Memory: ChromaDB (vector store)
- Ops: Docker + GitHub Actions

## Structure
- `/backend` — FastAPI app
- `/frontend` — React + Vite app

## Local development
(Backend and frontend run instructions — filled in as the build progresses.)
