"""Small OpenAI-compatible BGE-M3 embedding service for single-GPU deployments."""

from __future__ import annotations

from contextlib import asynccontextmanager
import os
from typing import Any

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from starlette.concurrency import run_in_threadpool


MODEL_PATH = os.environ.get("EMBEDDING_MODEL_PATH", "models/bge-m3")
SERVED_MODEL_NAME = os.environ.get("EMBEDDING_SERVED_MODEL_NAME", "BAAI/bge-m3")
DEVICE = os.environ.get("EMBEDDING_DEVICE", "cpu")
BATCH_SIZE = int(os.environ.get("EMBEDDING_BATCH_SIZE", "8"))

_model: Any | None = None


def normalize_inputs(value: str | list[str]) -> list[str]:
    texts = [value] if isinstance(value, str) else value
    if not texts or any(not isinstance(text, str) or not text.strip() for text in texts):
        raise ValueError("input must be a non-empty string or list of non-empty strings")
    return texts


class EmbeddingRequest(BaseModel):
    input: str | list[str]
    model: str = SERVED_MODEL_NAME
    encoding_format: str = "float"


def _load_model():
    from sentence_transformers import SentenceTransformer

    return SentenceTransformer(MODEL_PATH, device=DEVICE, trust_remote_code=True)


@asynccontextmanager
async def lifespan(_: FastAPI):
    global _model
    _model = await run_in_threadpool(_load_model)
    yield
    _model = None


app = FastAPI(title="BGE-M3 OpenAI-compatible embedding service", lifespan=lifespan)


@app.get("/health")
async def health() -> dict[str, object]:
    return {"status": "ok" if _model is not None else "loading", "model": SERVED_MODEL_NAME}


@app.get("/v1/models")
async def models() -> dict[str, object]:
    return {"object": "list", "data": [{"id": SERVED_MODEL_NAME, "object": "model"}]}


@app.post("/v1/embeddings")
async def embeddings(request: EmbeddingRequest) -> dict[str, object]:
    if _model is None:
        raise HTTPException(status_code=503, detail="embedding model is still loading")
    if request.encoding_format != "float":
        raise HTTPException(status_code=400, detail="only float embedding output is supported")
    try:
        texts = normalize_inputs(request.input)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    vectors = await run_in_threadpool(
        lambda: _model.encode(
            texts,
            batch_size=BATCH_SIZE,
            normalize_embeddings=True,
            convert_to_numpy=True,
            show_progress_bar=False,
        )
    )
    data = [
        {"object": "embedding", "index": index, "embedding": vector.tolist()}
        for index, vector in enumerate(vectors)
    ]
    approximate_tokens = sum(max(1, len(text) // 4) for text in texts)
    return {
        "object": "list",
        "model": request.model or SERVED_MODEL_NAME,
        "data": data,
        "usage": {"prompt_tokens": approximate_tokens, "total_tokens": approximate_tokens},
    }

