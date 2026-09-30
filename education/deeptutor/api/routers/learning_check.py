"""HTTP endpoints for one private check after a teaching explanation."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from deeptutor.services.learning_check import (
    AnswerConflict,
    InvalidGeneratedQuestion,
    LearningCheckService,
)
from deeptutor.services.session import get_sqlite_session_store

router = APIRouter()


class GenerateRequest(BaseModel):
    session_id: str = Field(min_length=1, max_length=200)
    knowledge_point: str = Field(min_length=1, max_length=500)
    lesson_question: str = Field(min_length=1, max_length=4000)
    lesson_answer: str = Field(min_length=1, max_length=20000)
    difficulty: str = Field(default="", pattern=r"^(|easy|medium|hard)$")
    kb_name: str = Field(default="", max_length=200)


class SubmitRequest(BaseModel):
    answer: str = Field(min_length=1, max_length=2000)


@router.post("")
async def generate(payload: GenerateRequest):
    if not all(
        value.strip()
        for value in (
            payload.session_id,
            payload.knowledge_point,
            payload.lesson_question,
            payload.lesson_answer,
        )
    ):
        raise HTTPException(422, "Required text fields must not be blank")
    try:
        return await LearningCheckService(get_sqlite_session_store()).generate(
            session_id=payload.session_id.strip(),
            knowledge_point=payload.knowledge_point.strip(),
            lesson_question=payload.lesson_question.strip(),
            lesson_answer=payload.lesson_answer.strip(),
            difficulty=payload.difficulty,
            kb_name=payload.kb_name.strip(),
        )
    except LookupError as exc:
        raise HTTPException(404, str(exc)) from exc
    except InvalidGeneratedQuestion as exc:
        raise HTTPException(502, str(exc)) from exc


@router.post("/{check_id}/submit")
async def submit(check_id: str, payload: SubmitRequest):
    if not payload.answer.strip():
        raise HTTPException(422, "Answer must not be blank")
    try:
        return await LearningCheckService(get_sqlite_session_store()).submit(
            check_id=check_id, answer=payload.answer.strip()
        )
    except LookupError as exc:
        raise HTTPException(404, str(exc)) from exc
    except TimeoutError as exc:
        raise HTTPException(410, str(exc)) from exc
    except AnswerConflict as exc:
        raise HTTPException(409, str(exc)) from exc
    except InvalidGeneratedQuestion as exc:
        raise HTTPException(502, str(exc)) from exc
