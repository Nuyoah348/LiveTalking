"""One private, objective question after a lesson, filed into the existing practice bank."""

from __future__ import annotations

import asyncio
from contextlib import closing
import json
import sqlite3
import time
import uuid
from pathlib import Path
from typing import Any

from deeptutor.services.practice.answers import check_answer


class InvalidGeneratedQuestion(ValueError):
    """The generator did not return a safely gradable choice question."""


class AnswerConflict(ValueError):
    """A different answer was already submitted for this check."""


async def generate_choice_question(
    *,
    session_id: str,
    knowledge_point: str,
    lesson_question: str,
    lesson_answer: str,
    difficulty: str = "",
    kb_name: str = "",
) -> dict[str, Any]:
    """Use DeepQuestion with the completed explanation as its question context."""
    from deeptutor.agents.question.pipeline import QuestionPipeline
    from deeptutor.core.context import UnifiedContext
    from deeptutor.runtime.stream_bus import StreamBus
    from deeptutor.services.settings.interface_settings import get_response_language

    prompt = (
        f"Create one new multiple-choice understanding check for the knowledge point: "
        f"{knowledge_point}. It must test the same idea as the completed lesson, "
        "without repeating the student's original question."
    )
    lesson_context = (
        f"Original student question:\n{lesson_question}\n\n"
        f"Tutor's final explanation:\n{lesson_answer}"
    )
    stream = StreamBus()
    try:
        result = await QuestionPipeline(
            language=get_response_language(default="en"), kb_name=kb_name or None
        ).run(
            context=UnifiedContext(
                session_id=session_id,
                user_message=prompt,
                active_capability="deep_question",
                knowledge_bases=[kb_name] if kb_name else [],
            ),
            user_message=prompt,
            num_questions=1,
            difficulty=difficulty,
            question_types=["choice"],
            per_type_counts={"choice": 1},
            conversation_context=lesson_context,
            stream=stream,
        )
    finally:
        await stream.close()
    results = (result.get("summary") or {}).get("results") or []
    if len(results) != 1 or not isinstance(results[0], dict):
        raise InvalidGeneratedQuestion("DeepQuestion did not produce one question")
    if (results[0].get("metadata") or {}).get("error"):
        raise InvalidGeneratedQuestion("DeepQuestion could not produce a valid question")
    question = results[0].get("qa_pair")
    if not isinstance(question, dict):
        raise InvalidGeneratedQuestion("DeepQuestion returned an invalid question")
    return question


def _validate_question(raw: dict[str, Any]) -> dict[str, Any]:
    options = raw.get("options")
    key = str(raw.get("correct_answer") or "").strip().upper()
    if (
        raw.get("question_type") != "choice"
        or not str(raw.get("question") or "").strip()
        or not isinstance(options, dict)
        or set(options) != {"A", "B", "C", "D"}
        or not all(isinstance(value, str) and value.strip() for value in options.values())
        or key not in options
    ):
        raise InvalidGeneratedQuestion("DeepQuestion returned an ungradable question")
    question = dict(raw)
    question["correct_answer"] = key
    return question


def _connect(db_path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute(
        """CREATE TABLE IF NOT EXISTS learning_checks (
            check_id TEXT PRIMARY KEY,
            session_id TEXT NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
            knowledge_point TEXT NOT NULL,
            question_json TEXT NOT NULL,
            expires_at REAL NOT NULL,
            submitted_answer TEXT,
            is_correct INTEGER
        )"""
    )
    return conn


def _session_active(db_path: Path, session_id: str) -> bool:
    with closing(sqlite3.connect(db_path)) as conn:
        return conn.execute(
            "SELECT 1 FROM sessions WHERE id = ? AND deleted_at IS NULL", (session_id,)
        ).fetchone() is not None


def _save_check(db_path: Path, session_id: str, knowledge_point: str, question: dict) -> dict:
    check_id = uuid.uuid4().hex
    expires_at = time.time() + 7 * 86400
    question = {**question, "question_id": check_id}
    with closing(_connect(db_path)) as conn, conn:
        cursor = conn.execute(
            """INSERT INTO learning_checks
               SELECT ?, ?, ?, ?, ?, NULL, NULL
               WHERE EXISTS (SELECT 1 FROM sessions WHERE id = ? AND deleted_at IS NULL)""",
            (check_id, session_id, knowledge_point, json.dumps(question), expires_at, session_id),
        )
        if cursor.rowcount != 1:
            raise LookupError("Session not found")
    return {
        "check_id": check_id,
        "question_id": check_id,
        "knowledge_point": knowledge_point,
        "question": question["question"],
        "question_type": "choice",
        "options": question["options"],
        "expires_at": expires_at,
    }


def _claim_answer(db_path: Path, check_id: str, answer: str) -> tuple[dict, str, bool]:
    with closing(_connect(db_path)) as conn, conn:
        conn.execute("BEGIN IMMEDIATE")
        row = conn.execute(
            """SELECT c.* FROM learning_checks c
               JOIN sessions s ON s.id = c.session_id AND s.deleted_at IS NULL
               WHERE c.check_id = ?""",
            (check_id,),
        ).fetchone()
        if row is None:
            raise LookupError("Learning check not found")
        if row["expires_at"] < time.time() and row["submitted_answer"] is None:
            raise TimeoutError("Learning check expired")
        if row["submitted_answer"] is not None and row["submitted_answer"] != answer:
            raise AnswerConflict("This check already has a different answer")
        question = json.loads(row["question_json"])
        if row["submitted_answer"] is None:
            correct = check_answer(question, answer)
            if correct is None:
                raise InvalidGeneratedQuestion("Stored question cannot be graded")
            conn.execute(
                "UPDATE learning_checks SET submitted_answer = ?, is_correct = ? WHERE check_id = ?",
                (answer, int(correct), check_id),
            )
        else:
            correct = bool(row["is_correct"])
        return question, row["session_id"], correct


class LearningCheckService:
    def __init__(self, store: Any):
        self.store = store

    async def generate(
        self,
        *,
        session_id: str,
        knowledge_point: str,
        lesson_question: str,
        lesson_answer: str,
        difficulty: str = "",
        kb_name: str = "",
    ) -> dict:
        if not await asyncio.to_thread(_session_active, self.store.db_path, session_id):
            raise LookupError("Session not found")
        try:
            raw = await generate_choice_question(
                session_id=session_id,
                knowledge_point=knowledge_point,
                lesson_question=lesson_question,
                lesson_answer=lesson_answer,
                difficulty=difficulty,
                kb_name=kb_name,
            )
        except InvalidGeneratedQuestion:
            raise
        except Exception as exc:
            raise InvalidGeneratedQuestion("DeepQuestion generation failed") from exc
        question = _validate_question(raw)
        question.update(
            lesson_question=lesson_question,
            lesson_answer=lesson_answer,
            kb_name=kb_name,
        )
        return await asyncio.to_thread(
            _save_check, self.store.db_path, session_id, knowledge_point, question
        )

    async def submit(self, *, check_id: str, answer: str) -> dict:
        question, session_id, correct = await asyncio.to_thread(
            _claim_answer, self.store.db_path, check_id, answer
        )
        try:
            await self.store.upsert_notebook_entries(
                session_id,
                [
                    {
                        **question,
                        "question_id": check_id,
                        "turn_id": check_id,
                        "source": "deep_question",
                        "assessment_type": "focus_check",
                        "result": "correct" if correct else "incorrect",
                        "user_answer": answer,
                        "is_correct": correct,
                    }
                ],
            )
        except ValueError as exc:
            raise LookupError("Session not found") from exc
        entry = await self.store.find_notebook_entry(session_id, check_id, turn_id=check_id)
        if entry is None:
            raise RuntimeError("Learning check could not be recorded")
        entry_id = entry["id"]
        return {
            "check_id": check_id,
            "correct": correct,
            "notebook_entry_id": entry_id,
            "next_action": (
                {"kind": "continue_lesson"}
                if correct
                else {"kind": "practice", "entry_id": entry_id}
            ),
        }
