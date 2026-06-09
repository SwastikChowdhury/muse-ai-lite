from fastapi import FastAPI

app = FastAPI(title="muse-ai-lite")


@app.get("/health")
def health():
    return {"status": "ok"}