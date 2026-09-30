"""OpenAI-compatible transcription endpoint backed by local SenseVoiceSmall."""

from __future__ import annotations

from contextlib import asynccontextmanager
import os
from pathlib import Path
import re
import tempfile
from typing import Any

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from starlette.concurrency import run_in_threadpool


MODEL_PATH = os.environ.get("STT_MODEL_PATH", "models/SenseVoiceSmall")
SERVED_MODEL_NAME = os.environ.get("STT_SERVED_MODEL_NAME", "FunAudioLLM/SenseVoiceSmall")
DEVICE = os.environ.get("STT_DEVICE", "cpu")

_model: Any | None = None
_EVENT_TAG = re.compile(r"<\|[^|>]+\|>")


def clean_transcript(text: str) -> str:
    return _EVENT_TAG.sub("", text or "").strip()


def _load_model():
    from funasr import AutoModel

    return AutoModel(
        model=MODEL_PATH,
        trust_remote_code=True,
        disable_update=True,
        device=DEVICE,
    )


def _transcribe_file(path: str, language: str) -> str:
    assert _model is not None
    result = _model.generate(
        input=path,
        cache={},
        language=language or "auto",
        use_itn=True,
        batch_size_s=60,
    )
    if not result or not isinstance(result, list):
        return ""
    row = result[0] if isinstance(result[0], dict) else {}
    text = str(row.get("text") or "")
    try:
        from funasr.utils.postprocess_utils import rich_transcription_postprocess

        text = rich_transcription_postprocess(text)
    except (ImportError, AttributeError):
        pass
    return clean_transcript(text)


@asynccontextmanager
async def lifespan(_: FastAPI):
    global _model
    _model = await run_in_threadpool(_load_model)
    yield
    _model = None


app = FastAPI(title="SenseVoice OpenAI-compatible STT service", lifespan=lifespan)


@app.get("/health")
async def health() -> dict[str, object]:
    return {"status": "ok" if _model is not None else "loading", "model": SERVED_MODEL_NAME}


@app.get("/v1/models")
async def models() -> dict[str, object]:
    return {"object": "list", "data": [{"id": SERVED_MODEL_NAME, "object": "model"}]}


@app.post("/v1/audio/transcriptions")
async def transcriptions(
    file: UploadFile = File(...),
    model: str = Form(SERVED_MODEL_NAME),
    language: str = Form("auto"),
    response_format: str = Form("json"),
):
    del model
    if _model is None:
        raise HTTPException(status_code=503, detail="speech model is still loading")
    audio = await file.read()
    if not audio:
        raise HTTPException(status_code=400, detail="audio file is empty")

    suffix = Path(file.filename or "audio.wav").suffix.lower()
    if not re.fullmatch(r"\.[a-z0-9]{1,8}", suffix):
        suffix = ".wav"
    temp_path = ""
    try:
        with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as handle:
            handle.write(audio)
            temp_path = handle.name
        text = await run_in_threadpool(_transcribe_file, temp_path, language)
    finally:
        if temp_path:
            Path(temp_path).unlink(missing_ok=True)

    if response_format == "text":
        return text
    if response_format == "verbose_json":
        return {"text": text, "segments": [{"start": 0.0, "end": 0.0, "text": text}]}
    return {"text": text}

