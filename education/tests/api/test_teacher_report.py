"""Teacher report exposes recorded activity only for the request account."""

from __future__ import annotations

from dataclasses import dataclass

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from deeptutor.api.routers import teacher


@dataclass
class Unit:
    covered: bool


@dataclass
class Course:
    id: str
    name: str
    status: str
    syllabus: list[Unit]


def test_report_projects_scoped_records_without_class_metrics(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: list[str] = []

    class User:
        id = "learner-1"
        username = "Learner One"

    class Courses:
        def list_courses(self):
            seen.append("courses")
            return [Course("algebra", "Algebra", "active", [Unit(True), Unit(False)])]

    async def workspace_reader(reader):
        return [{**row, "content_workspace_id": "", "content_workspace_name": ""} for row in await reader()], []

    async def practice_summary(**kwargs):
        assert kwargs == {"timezone": "Asia/Shanghai", "all_workspaces": True}
        return {"total": 8, "mistakes": 3, "due": 2, "reviewed_today": 1, "unavailable_workspaces": []}

    async def analytics(**kwargs):
        assert kwargs == {"timezone": "Asia/Shanghai", "days": 30, "all_workspaces": True}
        return {"totals": {"reviews": 6}, "daily": [{"date": "2026-09-28", "reviews": 1}]}

    async def mastery():
        return {
            "assessed_points": 1,
            "weak_points": [{
                "path_id": "path-1", "path_name": "Fractions",
                "knowledge_point_id": "addition", "knowledge_point": "Add fractions",
                "mastery_percent": 40, "quiz_attempts": 2,
                "content_workspace_id": "math",
            }],
            "error_types": {"application": 1},
            "unavailable_workspaces": [], "unavailable_paths": 0,
        }

    monkeypatch.setattr(teacher, "get_current_user", lambda: User())
    monkeypatch.setattr(teacher, "get_course_service", lambda: Courses())
    monkeypatch.setattr(teacher, "read_workspace_indexes", workspace_reader)
    monkeypatch.setattr(teacher, "summary", practice_summary)
    monkeypatch.setattr(teacher, "practice_analytics", analytics)
    monkeypatch.setattr(teacher, "read_member_mastery", mastery)

    app = FastAPI()
    app.include_router(teacher.router, prefix="/api/teacher")
    response = TestClient(app).get("/api/teacher/report?timezone=Asia/Shanghai")

    assert response.status_code == 200
    assert response.json() == {
        "scope": "current_account",
        "account": {"id": "learner-1", "name": "Learner One"},
        "practice": {
            "questions": 8, "mistakes": 3, "due": 2, "reviewed_today": 1,
            "reviews_last_30_days": 6,
            "daily": [{"date": "2026-09-28", "reviews": 1}],
        },
        "courses": [{
            "id": "algebra", "name": "Algebra", "status": "active",
            "units": 2, "covered_units": 1,
            "content_workspace_id": "", "content_workspace_name": "",
        }],
        "unavailable_workspaces": [],
        "unavailable_paths": 0,
        "next_steps": [
            {
                "kind": "weak_point", "title": "复习 Add fractions",
                "reason": "Fractions 的该目标掌握度为 40%，来自 2 次测验。",
                "target_label": "打开掌握路径",
                "target_path": "/learning/mastery/path-1",
                "content_workspace_id": "math",
            },
            {
                "kind": "due_review", "title": "完成 2 道到期复习题",
                "reason": "当前账号有 2 道题已到复习时间。",
                "target_label": "打开今日复习",
                "target_path": "/learning/practice",
                "content_workspace_id": "",
            },
        ],
        "recommendation_note": "建议仅依据已读取的测评和练习记录；部分工作区不可读时可能遗漏建议。",
    }
    assert seen == ["courses"]


def test_error_recommendation_requires_unresolved_record_with_path() -> None:
    practice = {"due": 0}
    mastery = {
        "weak_points": [],
        "error_records": [{
            "path_id": "path-2", "path_name": "Geometry",
            "knowledge_point": "Angles", "error_type": "application",
            "content_workspace_id": "geometry",
        }],
    }
    steps = teacher._next_steps(practice, mastery)
    assert steps == [{
        "kind": "error_record", "title": "回看 Angles 的错误诊断",
        "reason": "Geometry 中有未结案的应用错误记录。",
        "target_label": "打开掌握路径",
        "target_path": "/learning/mastery/path-2",
        "content_workspace_id": "geometry",
    }]
    assert teacher._next_steps(practice, {"weak_points": [], "error_types": {"application": 1}}) == []
