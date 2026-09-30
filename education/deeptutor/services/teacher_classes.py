"""Consent-based class membership, separate from private learning stores."""

from __future__ import annotations

from contextlib import contextmanager
import hashlib
from pathlib import Path
import secrets
import sqlite3
import time
from uuid import uuid4

from deeptutor.multi_user import paths
from deeptutor.utils.secret_files import ensure_private_directory, ensure_private_file


class ClassNotFound(Exception):
    pass


class InvalidInvite(Exception):
    pass


class ClassStore:
    def __init__(self, path: Path | None = None) -> None:
        self.path = path or paths.SYSTEM_ROOT / "teacher_classes.sqlite3"

    @contextmanager
    def connect(self):
        ensure_private_directory(self.path.parent)
        conn = sqlite3.connect(self.path, timeout=15)
        ensure_private_file(self.path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys=ON")
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS teacher_classes (
                id TEXT PRIMARY KEY,
                owner_id TEXT NOT NULL,
                name TEXT NOT NULL,
                invite_digest TEXT NOT NULL UNIQUE,
                created_at REAL NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_teacher_classes_owner ON teacher_classes(owner_id);
            CREATE TABLE IF NOT EXISTS teacher_class_members (
                class_id TEXT NOT NULL REFERENCES teacher_classes(id) ON DELETE CASCADE,
                user_id TEXT NOT NULL,
                joined_at REAL NOT NULL,
                PRIMARY KEY (class_id, user_id)
            );
            CREATE INDEX IF NOT EXISTS idx_teacher_class_members_user ON teacher_class_members(user_id);
        """)
        try:
            yield conn
            conn.commit()
        except BaseException:
            conn.rollback()
            raise
        finally:
            conn.close()

    def create(self, owner_id: str, name: str) -> dict:
        code = secrets.token_urlsafe(24)
        class_id = f"class_{uuid4().hex}"
        now = time.time()
        with self.connect() as conn:
            conn.execute(
                "INSERT INTO teacher_classes(id, owner_id, name, invite_digest, created_at) VALUES(?,?,?,?,?)",
                (class_id, owner_id, name, _digest(code), now),
            )
        return {"id": class_id, "name": name, "created_at": now, "invite_code": code}

    def owned(self, owner_id: str) -> list[dict]:
        with self.connect() as conn:
            rows = conn.execute("""
                SELECT c.id, c.name, c.created_at, COUNT(m.user_id) AS members
                FROM teacher_classes c LEFT JOIN teacher_class_members m ON m.class_id=c.id
                WHERE c.owner_id=? GROUP BY c.id ORDER BY c.created_at DESC
            """, (owner_id,)).fetchall()
        return [dict(row) for row in rows]

    def joined(self, user_id: str) -> list[dict]:
        with self.connect() as conn:
            rows = conn.execute("""
                SELECT c.id, c.name, m.joined_at FROM teacher_class_members m
                JOIN teacher_classes c ON c.id=m.class_id
                WHERE m.user_id=? ORDER BY m.joined_at DESC
            """, (user_id,)).fetchall()
        return [dict(row) for row in rows]

    def join(self, user_id: str, invite_code: str) -> dict:
        with self.connect() as conn:
            row = conn.execute(
                "SELECT id, owner_id, name FROM teacher_classes WHERE invite_digest=?",
                (_digest(invite_code),),
            ).fetchone()
            if row is None:
                raise InvalidInvite()
            if row["owner_id"] == user_id:
                raise InvalidInvite()
            conn.execute(
                "INSERT OR IGNORE INTO teacher_class_members(class_id, user_id, joined_at) VALUES(?,?,?)",
                (row["id"], user_id, time.time()),
            )
        return {"id": row["id"], "name": row["name"]}

    def renew_invite(self, class_id: str, owner_id: str) -> str:
        code = secrets.token_urlsafe(24)
        with self.connect() as conn:
            result = conn.execute(
                "UPDATE teacher_classes SET invite_digest=? WHERE id=? AND owner_id=?",
                (_digest(code), class_id, owner_id),
            )
            if result.rowcount == 0:
                raise ClassNotFound()
        return code

    def leave(self, class_id: str, user_id: str) -> None:
        with self.connect() as conn:
            result = conn.execute(
                "DELETE FROM teacher_class_members WHERE class_id=? AND user_id=?",
                (class_id, user_id),
            )
            if result.rowcount == 0:
                raise ClassNotFound()

    def members(self, class_id: str, owner_id: str) -> tuple[dict, list[str]]:
        with self.connect() as conn:
            row = conn.execute(
                "SELECT id, name FROM teacher_classes WHERE id=? AND owner_id=?",
                (class_id, owner_id),
            ).fetchone()
            if row is None:
                raise ClassNotFound()
            members = conn.execute(
                "SELECT user_id FROM teacher_class_members WHERE class_id=? ORDER BY joined_at, user_id",
                (class_id,),
            ).fetchall()
        return dict(row), [member["user_id"] for member in members]

    def is_member(self, class_id: str, user_id: str) -> bool:
        with self.connect() as conn:
            return conn.execute(
                "SELECT 1 FROM teacher_class_members WHERE class_id=? AND user_id=?",
                (class_id, user_id),
            ).fetchone() is not None


def _digest(code: str) -> str:
    return hashlib.sha256(code.encode("utf-8")).hexdigest()
