"""A post-explanation check stays private until it has been answered."""

import asyncio
import json
import sqlite3

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest

from deeptutor.api.routers import learning_check
from deeptutor.services import learning_check as check_service
from deeptutor.services.practice.storage import PracticeStore
from deeptutor.services.session.sqlite_store import SQLiteSessionStore


@pytest.fixture
def client(tmp_path, monkeypatch):
    store = SQLiteSessionStore(tmp_path / "checks.db")
    asyncio.run(store.create_session(session_id="lesson"))
    monkeypatch.setattr(learning_check, "get_sqlite_session_store", lambda: store)

    async def generated(**kwargs):
        assert kwargs["knowledge_point"] == "fraction addition"
        assert kwargs["lesson_question"] == "How do fractions add?"
        assert kwargs["lesson_answer"] == "Use a common denominator."
        assert kwargs["kb_name"] == "math-book"
        return {
            "question_id": "model-question",
            "question": "1/2 + 1/2 = ?",
            "question_type": "choice",
            "options": {"A": "1/2", "B": "1", "C": "2", "D": "0"},
            "correct_answer": "B",
            "explanation": "The halves make one whole.",
            "difficulty": "easy",
        }

    monkeypatch.setattr(check_service, "generate_choice_question", generated)
    app = FastAPI()
    app.include_router(learning_check.router, prefix="/api/learning-checks")
    with TestClient(app) as test_client:
        yield store, test_client


def test_wrong_answer_enters_existing_practice_without_leaking_key(client):
    store, http = client
    issued = http.post(
        "/api/learning-checks",
        json={
            "session_id": "lesson", "knowledge_point": "fraction addition",
            "lesson_question": "How do fractions add?",
            "lesson_answer": "Use a common denominator.", "kb_name": "math-book",
        },
    )
    assert issued.status_code == 200
    question = issued.json()
    assert question["question"] == "1/2 + 1/2 = ?"
    assert "correct_answer" not in question
    assert "explanation" not in question
    assert asyncio.run(store.find_notebook_entry("lesson", question["question_id"])) is None
    with sqlite3.connect(store.db_path) as conn:
        saved = json.loads(conn.execute(
            "SELECT question_json FROM learning_checks WHERE check_id = ?",
            (question["check_id"],),
        ).fetchone()[0])
    assert (saved["lesson_question"], saved["lesson_answer"], saved["kb_name"]) == (
        "How do fractions add?", "Use a common denominator.", "math-book"
    )

    submitted = http.post(
        f"/api/learning-checks/{question['check_id']}/submit", json={"answer": "A"}
    )
    assert submitted.status_code == 200
    result = submitted.json()
    assert result["correct"] is False
    assert result["next_action"]["kind"] == "practice"
    assert "correct_answer" not in result
    entry = asyncio.run(store.get_notebook_entry(result["notebook_entry_id"]))
    assert entry["result"] == "incorrect"
    assert entry["knowledge_point_id"] == ""
    assert PracticeStore(store.db_path).state(entry["id"])["is_mistake"] == 1


def test_correct_answer_is_recorded_and_duplicate_is_idempotent(client):
    store, http = client
    question = http.post(
        "/api/learning-checks",
        json={
            "session_id": "lesson", "knowledge_point": "fraction addition",
            "lesson_question": "How do fractions add?",
            "lesson_answer": "Use a common denominator.", "kb_name": "math-book",
        },
    ).json()
    url = f"/api/learning-checks/{question['check_id']}/submit"
    first = http.post(url, json={"answer": "B"})
    second = http.post(url, json={"answer": "B"})
    assert first.status_code == second.status_code == 200
    assert first.json() == second.json()
    assert first.json()["correct"] is True
    entry = asyncio.run(store.get_notebook_entry(first.json()["notebook_entry_id"]))
    assert entry["result"] == "correct"
    assert PracticeStore(store.db_path).state(entry["id"])["is_mistake"] == 0
    assert http.post(url, json={"answer": "A"}).status_code == 409


def test_check_is_scoped_to_current_store(client, tmp_path, monkeypatch):
    _, http = client
    question = http.post(
        "/api/learning-checks",
        json={
            "session_id": "lesson", "knowledge_point": "fraction addition",
            "lesson_question": "How do fractions add?",
            "lesson_answer": "Use a common denominator.", "kb_name": "math-book",
        },
    ).json()
    other = SQLiteSessionStore(tmp_path / "another-user.db")
    monkeypatch.setattr(learning_check, "get_sqlite_session_store", lambda: other)
    assert http.post(
        f"/api/learning-checks/{question['check_id']}/submit", json={"answer": "B"}
    ).status_code == 404


def test_unknown_session_and_invalid_generated_key_fail_closed(client, monkeypatch):
    _, http = client
    assert http.post(
        "/api/learning-checks",
        json={
            "session_id": "missing", "knowledge_point": "fraction addition",
            "lesson_question": "How do fractions add?",
            "lesson_answer": "Use a common denominator.", "kb_name": "math-book",
        },
    ).status_code == 404

    async def invalid(**kwargs):
        return {
            "question_id": "q", "question": "Question", "question_type": "choice",
            "options": {"A": "yes", "B": "no"}, "correct_answer": "yes or no",
        }

    monkeypatch.setattr(check_service, "generate_choice_question", invalid)
    assert http.post(
        "/api/learning-checks",
        json={
            "session_id": "lesson", "knowledge_point": "fraction addition",
            "lesson_question": "How do fractions add?",
            "lesson_answer": "Use a common denominator.", "kb_name": "math-book",
        },
    ).status_code == 502


def test_blank_answer_is_rejected_without_recording_a_mistake(client):
    store, http = client
    question = http.post(
        "/api/learning-checks",
        json={
            "session_id": "lesson", "knowledge_point": "fraction addition",
            "lesson_question": "How do fractions add?",
            "lesson_answer": "Use a common denominator.", "kb_name": "math-book",
        },
    ).json()
    assert http.post(
        f"/api/learning-checks/{question['check_id']}/submit", json={"answer": "  "}
    ).status_code == 422
    assert asyncio.run(store.find_notebook_entry("lesson", question["question_id"])) is None


def test_deleted_session_cannot_create_or_submit_check(client):
    store, http = client
    payload = {
        "session_id": "lesson", "knowledge_point": "fraction addition",
        "lesson_question": "How do fractions add?",
        "lesson_answer": "Use a common denominator.", "kb_name": "math-book",
    }
    check_id = http.post("/api/learning-checks", json=payload).json()["check_id"]
    with sqlite3.connect(store.db_path) as conn:
        conn.execute("UPDATE sessions SET deleted_at = 1 WHERE id = 'lesson'")
    assert http.post("/api/learning-checks", json=payload).status_code == 404
    assert http.post(
        f"/api/learning-checks/{check_id}/submit", json={"answer": "B"}
    ).status_code == 404


def test_unanswered_check_expires_without_filing_an_attempt(client):
    store, http = client
    check_id = http.post(
        "/api/learning-checks",
        json={
            "session_id": "lesson", "knowledge_point": "fraction addition",
            "lesson_question": "How do fractions add?",
            "lesson_answer": "Use a common denominator.", "kb_name": "math-book",
        },
    ).json()["check_id"]
    with sqlite3.connect(store.db_path) as conn:
        conn.execute("UPDATE learning_checks SET expires_at = 1 WHERE check_id = ?", (check_id,))
    assert http.post(
        f"/api/learning-checks/{check_id}/submit", json={"answer": "B"}
    ).status_code == 410
    assert asyncio.run(store.find_notebook_entry("lesson", check_id, turn_id=check_id)) is None
