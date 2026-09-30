"""Account learning report and consent-based class reports.

Class members explicitly join; only the class owner can read their scoped
practice and Mastery Path summaries. The underlying account model has no
dedicated teacher role.
"""

from __future__ import annotations

import asyncio
import logging
from urllib.parse import quote

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from deeptutor.multi_user.context import get_current_user
from deeptutor.multi_user.identity import get_user_by_id
from deeptutor.multi_user.models import CurrentUser
from deeptutor.multi_user.paths import scope_for_user, user_context
from deeptutor.services.courses import get_course_service
from deeptutor.services.teacher_classes import ClassNotFound, ClassStore, InvalidInvite
from deeptutor.services.teacher_mastery import WEAK_MASTERY_THRESHOLD, read_member_mastery
from deeptutor.services.workspace.navigation import read_workspace_indexes

from .practice import practice_analytics, summary


router = APIRouter()
logger = logging.getLogger(__name__)

RECOMMENDATION_NOTE = "建议仅依据已读取的测评和练习记录；部分工作区不可读时可能遗漏建议。"
ERROR_NAMES = {"structural": "知识结构", "deviation": "理解偏差", "application": "应用", "metacognitive": "元认知"}


def _next_steps(practice: dict, mastery: dict, *, member_report: bool = False) -> list[dict]:
    """Return evidence-backed actions in stable priority order."""
    steps: list[dict] = []
    selected_paths: set[tuple[str, str]] = set()
    weak = sorted(
        mastery.get("weak_points", []),
        key=lambda point: (point["mastery_percent"], point.get("path_name", ""), point.get("knowledge_point", "")),
    )
    for point in weak:
        path_id = point.get("path_id")
        if not path_id:
            continue
        workspace_id = point.get("content_workspace_id", "")
        path_key = (workspace_id, path_id)
        if path_key in selected_paths:
            continue
        selected_paths.add(path_key)
        steps.append({
            "kind": "weak_point",
            "title": f"复习 {point['knowledge_point']}",
            "reason": f"{point['path_name']} 的该目标掌握度为 {point['mastery_percent']}%，" + (f"来自 {point['quiz_attempts']} 次测验。" if point["quiz_attempts"] else "来自定性评估。"),
            "target_label": "打开掌握路径",
            "target_path": None if member_report else f"/learning/mastery/{quote(path_id, safe='')}",
            "content_workspace_id": workspace_id,
        })
        if len(steps) == 2:
            break

    due = practice.get("due", 0)
    if due > 0:
        steps.append({
            "kind": "due_review",
            "title": f"完成 {due} 道到期复习题",
            "reason": f"{'该学生' if member_report else '当前账号'}有 {due} 道题已到复习时间。",
            "target_label": "打开今日复习",
            "target_path": None if member_report else "/learning/practice",
            "content_workspace_id": "",
        })

    for error in mastery.get("error_records", []):
        path_id = error.get("path_id")
        if not path_id:
            continue
        workspace_id = error.get("content_workspace_id", "")
        path_key = (workspace_id, path_id)
        if path_key in selected_paths:
            continue
        selected_paths.add(path_key)
        steps.append({
            "kind": "error_record",
            "title": f"回看 {error['knowledge_point']} 的错误诊断",
            "reason": f"{error['path_name']} 中有未结案的{ERROR_NAMES.get(error['error_type'], error['error_type'])}错误记录。",
            "target_label": "打开掌握路径",
            "target_path": None if member_report else f"/learning/mastery/{quote(path_id, safe='')}",
            "content_workspace_id": workspace_id,
        })
        break
    return steps


class CreateClassRequest(BaseModel):
    name: str = Field(min_length=1, max_length=80)


class JoinClassRequest(BaseModel):
    invite_code: str = Field(min_length=20, max_length=100)


def _known_account(user_id: str) -> tuple[str, dict]:
    identity = get_user_by_id(user_id)
    if identity is None or identity[1].get("disabled"):
        raise HTTPException(409, "Class sharing requires an active registered account")
    return identity


@router.get("/classes")
async def list_classes() -> dict:
    user = get_current_user()
    _known_account(user.id)
    store = ClassStore()
    return {"owned": store.owned(user.id), "joined": store.joined(user.id)}


@router.post("/classes")
async def create_class(payload: CreateClassRequest) -> dict:
    user = get_current_user()
    _known_account(user.id)
    name = " ".join(payload.name.split())
    if not name:
        raise HTTPException(422, "Class name cannot be empty")
    return ClassStore().create(user.id, name)


@router.post("/classes/join")
async def join_class(payload: JoinClassRequest) -> dict:
    user = get_current_user()
    _, identity = _known_account(user.id)
    if identity.get("role") != "user":
        raise HTTPException(403, "Only student accounts can join a class")
    try:
        return ClassStore().join(user.id, payload.invite_code.strip())
    except InvalidInvite as exc:
        raise HTTPException(404, "Invitation not found") from exc


@router.delete("/classes/{class_id}/membership")
async def leave_class(class_id: str) -> dict:
    try:
        ClassStore().leave(class_id, get_current_user().id)
    except ClassNotFound as exc:
        raise HTTPException(404, "Class membership not found") from exc
    return {"ok": True}


@router.post("/classes/{class_id}/invite")
async def renew_class_invite(class_id: str) -> dict:
    _known_account(get_current_user().id)
    try:
        code = ClassStore().renew_invite(class_id, get_current_user().id)
    except ClassNotFound as exc:
        raise HTTPException(404, "Class not found") from exc
    return {"invite_code": code}


@router.get("/classes/{class_id}/report")
async def get_class_report(
    class_id: str,
    timezone: str = Query(default="UTC", max_length=64),
) -> dict:
    """Read only members who joined this owner's class, in each member's scope."""
    from deeptutor.services.practice.scheduler import day_bounds

    try:
        day_bounds(timezone, 0)
    except Exception as exc:
        raise HTTPException(422, "Invalid timezone") from exc
    owner = get_current_user()
    _known_account(owner.id)
    store = ClassStore()
    try:
        classroom, member_ids = store.members(class_id, owner.id)
    except ClassNotFound as exc:
        raise HTTPException(404, "Class not found") from exc

    members = []
    unavailable_members = []
    weak_points = []
    error_types: dict[str, int] = {}
    assessed_points = 0
    for member_id in member_ids:
        identity = get_user_by_id(member_id)
        if identity is None or identity[1].get("disabled") or identity[1].get("role") != "user":
            continue
        username, record = identity
        member = CurrentUser(
            id=member_id,
            username=username,
            role="user",
            scope=scope_for_user(member_id, is_admin=False),
        )
        try:
            with user_context(member):
                practice = await summary(timezone=timezone, all_workspaces=True)
                trend = await practice_analytics(timezone=timezone, days=30, all_workspaces=True)
        except Exception:
            logger.warning("Could not read class member practice data", exc_info=True)
            if store.is_member(class_id, member_id):
                unavailable_members.append({"id": member_id, "name": username})
            continue
        mastery_unavailable = False
        try:
            with user_context(member):
                mastery = await read_member_mastery()
        except Exception:
            logger.warning("Could not read class member Mastery Path data", exc_info=True)
            mastery_unavailable = True
            mastery = {
                "assessed_points": 0,
                "weak_points": [],
                "error_types": {},
                "error_records": [],
                "unavailable_workspaces": [],
                "unavailable_paths": 0,
            }
        if not store.is_member(class_id, member_id):
            continue  # The student withdrew while this report was being prepared.
        assessed_points += mastery["assessed_points"]
        weak_points.extend(
            {**point, "student_id": member_id, "student_name": username}
            for point in mastery["weak_points"]
        )
        for error_type, count in mastery["error_types"].items():
            error_types[error_type] = error_types.get(error_type, 0) + count
        members.append({
            "id": member_id,
            "name": username,
            "questions": practice["total"],
            "mistakes": practice["mistakes"],
            "due": practice["due"],
            "reviewed_today": practice["reviewed_today"],
            "reviews_last_30_days": trend["totals"]["reviews"],
            "unavailable_workspaces": sorted(set(practice.get("unavailable_workspaces", [])) | set(mastery["unavailable_workspaces"])),
            "unavailable_paths": mastery["unavailable_paths"],
            "mastery_unavailable": mastery_unavailable,
            "next_steps": _next_steps(practice, mastery, member_report=True),
        })

    return {
        "scope": "joined_members",
        "class": classroom,
        "members": members,
        "unavailable_members": unavailable_members,
        "incomplete_member_count": len(unavailable_members)
        + sum(bool(member["unavailable_workspaces"] or member["unavailable_paths"] or member["mastery_unavailable"]) for member in members),
        "totals": {
            metric: sum(member[metric] for member in members)
            for metric in ("questions", "mistakes", "due", "reviewed_today", "reviews_last_30_days")
        },
        "mastery": {
            "assessed_points": assessed_points,
            "weak_points_count": len(weak_points),
            "weak_threshold_percent": round(WEAK_MASTERY_THRESHOLD * 100),
            "weak_points": sorted(weak_points, key=lambda point: (point["mastery_percent"], point["student_name"]))[:20],
            "error_types": error_types,
            "unresolved_error_records": sum(error_types.values()),
        },
        "metrics_note": "Practice counts are saved question activity. Weak points are assessed Mastery Path objectives below 60%; error types count unresolved structured diagnosis records.",
    }


@router.get("/report")
async def get_teacher_report(timezone: str = Query(default="UTC", max_length=64)) -> dict:
    """Summarize real course and practice records within the caller's account."""
    user = get_current_user()
    async def read_courses() -> list[dict]:
        courses = await asyncio.to_thread(get_course_service().list_courses)
        return [
            {
                "id": course.id,
                "name": course.name,
                "status": course.status,
                "units": len(course.syllabus),
                "covered_units": sum(unit.covered for unit in course.syllabus),
            }
            for course in courses
        ]

    courses, course_unavailable = await read_workspace_indexes(read_courses)
    practice = await summary(timezone=timezone, all_workspaces=True)
    trend = await practice_analytics(timezone=timezone, days=30, all_workspaces=True)
    try:
        mastery = await read_member_mastery()
    except Exception:
        logger.warning("Could not read account Mastery Path data", exc_info=True)
        mastery = {"weak_points": [], "error_records": [], "unavailable_workspaces": [], "unavailable_paths": 1}

    return {
        "scope": "current_account",
        "account": {"id": user.id, "name": user.username},
        "practice": {
            "questions": practice["total"],
            "mistakes": practice["mistakes"],
            "due": practice["due"],
            "reviewed_today": practice["reviewed_today"],
            "reviews_last_30_days": trend["totals"]["reviews"],
            "daily": [
                {"date": day["date"], "reviews": day["reviews"]}
                for day in trend["daily"]
            ],
        },
        "courses": courses,
        "unavailable_workspaces": sorted(
            set(course_unavailable) | set(practice.get("unavailable_workspaces", [])) | set(mastery.get("unavailable_workspaces", []))
        ),
        "unavailable_paths": mastery.get("unavailable_paths", 0),
        "next_steps": _next_steps(practice, mastery),
        "recommendation_note": RECOMMENDATION_NOTE,
    }
