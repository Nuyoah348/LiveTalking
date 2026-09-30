"""Read-only projections of a member's own Mastery Path records."""

from __future__ import annotations

import asyncio

from deeptutor.learning import policy
from deeptutor.learning.storage import LearningStore
from deeptutor.services.workspace.navigation import read_workspace_indexes


WEAK_MASTERY_THRESHOLD = 0.6
_UNRESOLVED_ERROR_STATUSES = {"active", "retrying", "review"}


def _workspace_rows() -> list[dict]:
    store = LearningStore()
    rows = []
    for path_id in store.list_all():
        try:
            progress = store.load(path_id)
            if progress is None:
                continue
            current_points = {
                point.id: point
                for module in progress.modules
                for point in module.knowledge_points
            }
            attempt_counts: dict[str, int] = {}
            for attempt in progress.quiz_attempts:
                if not attempt.voided and attempt.knowledge_point_id in current_points:
                    attempt_counts[attempt.knowledge_point_id] = (
                        attempt_counts.get(attempt.knowledge_point_id, 0) + 1
                    )
            path_name = policy.path_display_name(progress)
            for point in current_points.values():
                attempts = attempt_counts.get(point.id, 0)
                if not attempts and point.id not in progress.qualitative_mastery:
                    continue
                mastery = policy.display_mastery(progress, point)
                rows.append({"kind": "assessed_point"})
                if mastery < WEAK_MASTERY_THRESHOLD:
                    rows.append({
                        "kind": "weak_point",
                        "path_id": path_id,
                        "path_name": path_name,
                        "knowledge_point_id": point.id,
                        "knowledge_point": point.name,
                        "mastery_percent": round(mastery * 100),
                        "quiz_attempts": attempts,
                    })
            for error in progress.error_records:
                if (
                    error.knowledge_point_id in current_points
                    and error.status in _UNRESOLVED_ERROR_STATUSES
                ):
                    rows.append({
                        "kind": "error_type",
                        "error_type": error.error_type.value,
                        "path_id": path_id,
                        "path_name": path_name,
                        "knowledge_point_id": error.knowledge_point_id,
                        "knowledge_point": current_points[error.knowledge_point_id].name,
                    })
        except Exception:
            rows.append({"kind": "unavailable_path"})
    return rows


async def read_member_mastery() -> dict:
    async def read() -> list[dict]:
        return await asyncio.to_thread(_workspace_rows)

    rows, unavailable_workspaces = await read_workspace_indexes(read)
    error_types: dict[str, int] = {}
    for row in rows:
        if row["kind"] == "error_type":
            label = row["error_type"]
            error_types[label] = error_types.get(label, 0) + 1
    return {
        "weak_points": [row for row in rows if row["kind"] == "weak_point"],
        "assessed_points": sum(row["kind"] == "assessed_point" for row in rows),
        "error_types": error_types,
        "error_records": [row for row in rows if row["kind"] == "error_type"],
        "unavailable_workspaces": unavailable_workspaces,
        "unavailable_paths": sum(row["kind"] == "unavailable_path" for row in rows),
    }
