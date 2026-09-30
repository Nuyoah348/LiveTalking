"""Mastery reporting excludes untouched, voided, stale, and resolved evidence."""

from __future__ import annotations

from deeptutor.learning.models import (
    ErrorRecord,
    KnowledgePoint,
    LearningModule,
    LearningProgress,
    QuizAttempt,
)
from deeptutor.services import teacher_mastery


def test_workspace_projection_uses_assessed_current_points(monkeypatch) -> None:
    progress = LearningProgress(
        book_id="path-1",
        name="Fractions",
        modules=[LearningModule(
            id="module", name="Basics", order=0,
            knowledge_points=[
                KnowledgePoint(id="weak", name="Add fractions", type="procedure", module_id="module"),
                KnowledgePoint(id="strong", name="Compare", type="memory", module_id="module"),
                KnowledgePoint(id="untouched", name="Multiply", type="procedure", module_id="module"),
            ],
        )],
        mastery_levels={"weak": 0.4, "strong": 0.8, "untouched": 0.0},
        quiz_attempts=[
            QuizAttempt(question_id="q1", knowledge_point_id="weak", is_correct=False),
            QuizAttempt(question_id="q2", knowledge_point_id="strong", is_correct=True),
            QuizAttempt(question_id="q3", knowledge_point_id="untouched", is_correct=False, voided=True),
        ],
        error_records=[
            ErrorRecord(id="e1", question_id="q1", knowledge_point_id="weak", module_id="module", error_type="application"),
            ErrorRecord(id="e2", question_id="q2", knowledge_point_id="strong", module_id="module", error_type="deviation", status="graduated"),
            ErrorRecord(id="e3", question_id="old", knowledge_point_id="stale", module_id="module", error_type="structural"),
        ],
    )

    class Store:
        def list_all(self):
            return ["path-1"]

        def load(self, _path_id):
            return progress

    monkeypatch.setattr(teacher_mastery, "LearningStore", Store)
    rows = teacher_mastery._workspace_rows()
    assert sum(row["kind"] == "assessed_point" for row in rows) == 2
    weak = [row for row in rows if row["kind"] == "weak_point"]
    assert [row["knowledge_point"] for row in weak] == ["Add fractions"]
    assert weak[0]["path_id"] == "path-1"
    assert weak[0]["knowledge_point_id"] == "weak"
    assert [row["error_type"] for row in rows if row["kind"] == "error_type"] == ["application"]
    assert [row["path_id"] for row in rows if row["kind"] == "error_type"] == ["path-1"]
