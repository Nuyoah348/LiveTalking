"""Class invitation consent and owner-only report access."""

from __future__ import annotations

from fastapi import Depends, FastAPI, Header
from fastapi.testclient import TestClient
import pytest

from deeptutor.api.routers import teacher
from deeptutor.multi_user.context import get_current_user, reset_current_user, set_current_user
from deeptutor.multi_user.models import CurrentUser, UserScope
from deeptutor.services.teacher_classes import ClassStore


@pytest.fixture
def client(tmp_path, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    store = ClassStore(tmp_path / "system" / "classes.sqlite3")
    monkeypatch.setattr(teacher, "ClassStore", lambda: store)

    identities = {
        "owner": ("Teacher", {"id": "owner", "role": "user", "disabled": False}),
        "student": ("Student", {"id": "student", "role": "user", "disabled": False}),
        "stranger": ("Stranger", {"id": "stranger", "role": "user", "disabled": False}),
        "admin": ("Admin", {"id": "admin", "role": "admin", "disabled": False}),
    }
    monkeypatch.setattr(teacher, "get_user_by_id", identities.get)
    monkeypatch.setattr(
        teacher,
        "scope_for_user",
        lambda user_id, is_admin: UserScope("user", user_id, tmp_path / user_id),
    )

    async def summary(**kwargs):
        assert kwargs["all_workspaces"] is True
        assert get_current_user().id == "student"
        return {"total": 7, "mistakes": 2, "due": 1, "reviewed_today": 1, "unavailable_workspaces": []}

    async def analytics(**kwargs):
        assert kwargs["days"] == 30
        assert get_current_user().id == "student"
        return {"totals": {"reviews": 4}}

    async def mastery():
        assert get_current_user().id == "student"
        return {
            "assessed_points": 2,
            "weak_points": [{"kind": "weak_point", "path_id": "path-1", "path_name": "Algebra", "knowledge_point": "Fractions", "mastery_percent": 40, "quiz_attempts": 2}],
            "error_types": {"application": 1},
            "error_records": [],
            "unavailable_workspaces": [],
            "unavailable_paths": 0,
        }

    monkeypatch.setattr(teacher, "summary", summary)
    monkeypatch.setattr(teacher, "practice_analytics", analytics)
    monkeypatch.setattr(teacher, "read_member_mastery", mastery)

    async def actor(x_actor: str = Header()) -> None:
        username, record = identities[x_actor]
        role = record["role"]
        user = CurrentUser(
            id=x_actor,
            username=username,
            role=role,
            scope=UserScope("admin" if role == "admin" else "user", x_actor, tmp_path / x_actor),
        )
        token = set_current_user(user)
        try:
            yield
        finally:
            reset_current_user(token)

    app = FastAPI()
    app.include_router(teacher.router, prefix="/api/teacher", dependencies=[Depends(actor)])
    return TestClient(app)


def test_owner_report_requires_student_join_and_stops_after_leave(client: TestClient) -> None:
    created = client.post("/api/teacher/classes", headers={"X-Actor": "owner"}, json={"name": "Algebra"})
    assert created.status_code == 200
    class_id = created.json()["id"]
    code = created.json()["invite_code"]
    assert len(code) >= 20

    path = f"/api/teacher/classes/{class_id}/report"
    assert client.get(path, headers={"X-Actor": "stranger"}).status_code == 404
    assert client.get(path, headers={"X-Actor": "student"}).status_code == 404
    assert client.get(path, headers={"X-Actor": "owner"}).json()["members"] == []
    assert client.post("/api/teacher/classes/join", headers={"X-Actor": "admin"}, json={"invite_code": code}).status_code == 403
    assert client.post("/api/teacher/classes/join", headers={"X-Actor": "student"}, json={"invite_code": "x" * 30}).status_code == 404

    joined = client.post("/api/teacher/classes/join", headers={"X-Actor": "student"}, json={"invite_code": code})
    assert joined.status_code == 200
    report = client.get(path, headers={"X-Actor": "owner"}).json()
    assert report["scope"] == "joined_members"
    assert report["members"][0]["name"] == "Student"
    assert report["totals"] == {
        "questions": 7, "mistakes": 2, "due": 1,
        "reviewed_today": 1, "reviews_last_30_days": 4,
    }
    assert report["mastery"]["assessed_points"] == 2
    assert report["mastery"]["weak_points_count"] == 1
    assert report["mastery"]["weak_points"][0]["student_name"] == "Student"
    assert report["mastery"]["error_types"] == {"application": 1}
    assert [step["kind"] for step in report["members"][0]["next_steps"]] == ["weak_point", "due_review"]
    assert all(step["target_path"] is None for step in report["members"][0]["next_steps"])

    left = client.delete(f"/api/teacher/classes/{class_id}/membership", headers={"X-Actor": "student"})
    assert left.status_code == 200
    assert client.get(path, headers={"X-Actor": "owner"}).json()["members"] == []


def test_invite_code_is_not_in_class_listing(client: TestClient) -> None:
    created = client.post("/api/teacher/classes", headers={"X-Actor": "owner"}, json={"name": "Geometry"})
    code = created.json()["invite_code"]
    listing = client.get("/api/teacher/classes", headers={"X-Actor": "owner"})
    assert listing.status_code == 200
    assert code not in listing.text
    assert listing.json()["owned"][0]["members"] == 0

    path = f"/api/teacher/classes/{created.json()['id']}/invite"
    assert client.post(path, headers={"X-Actor": "stranger"}).status_code == 404
    renewed = client.post(path, headers={"X-Actor": "owner"})
    assert renewed.status_code == 200
    assert renewed.json()["invite_code"] != code
    assert client.post("/api/teacher/classes/join", headers={"X-Actor": "student"}, json={"invite_code": code}).status_code == 404
    assert client.post("/api/teacher/classes/join", headers={"X-Actor": "student"}, json={"invite_code": renewed.json()["invite_code"]}).status_code == 200


def test_failed_member_read_marks_report_incomplete(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    created = client.post("/api/teacher/classes", headers={"X-Actor": "owner"}, json={"name": "Science"}).json()
    client.post("/api/teacher/classes/join", headers={"X-Actor": "student"}, json={"invite_code": created["invite_code"]})
    client.post("/api/teacher/classes/join", headers={"X-Actor": "stranger"}, json={"invite_code": created["invite_code"]})

    async def unavailable(**_kwargs):
        if get_current_user().id == "stranger":
            raise RuntimeError("member store offline")
        return {"total": 7, "mistakes": 2, "due": 1, "reviewed_today": 1, "unavailable_workspaces": []}

    monkeypatch.setattr(teacher, "summary", unavailable)
    response = client.get(f"/api/teacher/classes/{created['id']}/report", headers={"X-Actor": "owner"})
    assert response.status_code == 200
    assert response.json()["unavailable_members"] == [{"id": "stranger", "name": "Stranger"}]
    assert response.json()["incomplete_member_count"] == 1
    assert response.json()["totals"]["questions"] == 7


def test_mastery_failure_keeps_practice_totals(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    created = client.post("/api/teacher/classes", headers={"X-Actor": "owner"}, json={"name": "Math"}).json()
    client.post("/api/teacher/classes/join", headers={"X-Actor": "student"}, json={"invite_code": created["invite_code"]})

    async def unavailable():
        raise RuntimeError("mastery store offline")

    monkeypatch.setattr(teacher, "read_member_mastery", unavailable)
    report = client.get(f"/api/teacher/classes/{created['id']}/report", headers={"X-Actor": "owner"}).json()
    assert report["totals"]["questions"] == 7
    assert report["members"][0]["mastery_unavailable"] is True
    assert [step["kind"] for step in report["members"][0]["next_steps"]] == ["due_review"]
    assert report["incomplete_member_count"] == 1


def test_disabled_owner_cannot_read_joined_student_report(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    created = client.post("/api/teacher/classes", headers={"X-Actor": "owner"}, json={"name": "Math"}).json()
    client.post("/api/teacher/classes/join", headers={"X-Actor": "student"}, json={"invite_code": created["invite_code"]})
    original_lookup = teacher.get_user_by_id

    def disabled_owner(user_id: str):
        if user_id == "owner":
            return ("Teacher", {"id": "owner", "role": "user", "disabled": True})
        return original_lookup(user_id)

    monkeypatch.setattr(teacher, "get_user_by_id", disabled_owner)
    response = client.get(f"/api/teacher/classes/{created['id']}/report", headers={"X-Actor": "owner"})
    assert response.status_code == 409
    assert "Student" not in response.text
