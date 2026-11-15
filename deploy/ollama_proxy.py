import asyncio
import hmac
import json
import os

import httpx
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse

TOKEN = os.environ.get("OLLAMA_PROXY_TOKEN")

if not TOKEN or len(TOKEN) < 32:
    raise RuntimeError("OLLAMA_PROXY_TOKEN must be at least 32 characters")

app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)
semaphore = asyncio.Semaphore(2)


@app.post("/v1/chat/completions")
async def chat(request: Request):
    authorization = request.headers.get("authorization", "")
    expected = f"Bearer {TOKEN}"

    if not hmac.compare_digest(authorization, expected):
        raise HTTPException(status_code=401, detail="Unauthorized")

    if request.headers.get("content-type", "").split(";")[0].strip().lower() != "application/json":
        raise HTTPException(status_code=415, detail="JSON required")

    if int(request.headers.get("content-length", "0")) > 131072:
        raise HTTPException(status_code=413, detail="Request too large")

    body = await request.body()

    if len(body) > 131072:
        raise HTTPException(status_code=413, detail="Request too large")

    try:
        payload = json.loads(body)
    except (ValueError, UnicodeDecodeError):
        raise HTTPException(status_code=400, detail="Invalid JSON")

    if not isinstance(payload, dict):
        raise HTTPException(status_code=400, detail="JSON object required")

    if payload.get("model") != "qwen3:8b":
        raise HTTPException(status_code=403, detail="Model not allowed")

    if payload.get("stream", False) is not False:
        raise HTTPException(status_code=400, detail="Streaming disabled")

    messages = payload.get("messages")
    if not isinstance(messages, list) or not (1 <= len(messages) <= 10):
        raise HTTPException(status_code=400, detail="Invalid messages")

    if any(
        not isinstance(m, dict)
        or m.get("role") not in ("system", "user", "assistant")
        or not isinstance(m.get("content"), str)
        for m in messages
    ):
        raise HTTPException(status_code=400, detail="Invalid message format")

    if payload.get("max_tokens", 500) > 1024:
        raise HTTPException(status_code=400, detail="Token limit exceeded")

    async with semaphore:
        try:
            async with httpx.AsyncClient(timeout=120.0) as client:
                result = await client.post(
                    "http://127.0.0.1:11434/v1/chat/completions",
                    content=body,
                    headers={"Content-Type": "application/json"},
                )
        except httpx.RequestError:
            raise HTTPException(status_code=502, detail="Local Ollama unavailable")

    return JSONResponse(
        status_code=result.status_code,
        content=result.json(),
    )
