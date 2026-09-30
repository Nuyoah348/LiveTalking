"""Teaching answers consumed by the digital-human presentation page."""

import asyncio
import re
from contextlib import aclosing

from fastapi import APIRouter
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from deeptutor.app import DeepTutorApp
from deeptutor.services.learning_diagnosis import LearningDifficulty, build_learning_prompt


router = APIRouter()


class AskRequest(BaseModel):
    text: str = Field(min_length=1, max_length=4000)
    session_id: str | None = None
    capability: str = "chat"
    knowledge_bases: list[str] = Field(default_factory=list)
    difficulty: LearningDifficulty | None = None
    student_note: str | None = Field(default=None, max_length=200)


def speech_segments(answer: str, limit: int = 120) -> list[str]:
    """Split a completed answer into short, ordered TTS requests."""
    answer = re.sub(r"!?\[([^\]]+)\]\([^)]+\)", r"\1", answer)
    answer = re.sub(r"(?m)^\s{0,3}#{1,6}\s+", "", answer)
    answer = answer.replace("**", "").replace("__", "").replace("`", "")
    segments = []
    for sentence in re.findall(r"[^。！？!?；;，,]+[。！？!?；;，,]?", answer):
        sentence = sentence.strip()
        while sentence:
            segments.append(sentence[:limit])
            sentence = sentence[limit:]
    return segments


def visible_sources(raw_sources: list[object]) -> list[dict]:
    """Expose actual retrieved material, omitting a RAG query echo."""
    result = []
    seen = set()
    for raw in raw_sources:
        if not isinstance(raw, dict):
            continue
        title = str(raw.get("title") or raw.get("filename") or raw.get("source") or "").strip()
        content = str(raw.get("content") or raw.get("snippet") or raw.get("content_preview") or "").strip()
        if not title and not content:
            continue
        title = re.split(r"[/\\]", title)[-1][:180] or "检索片段"
        item = {"title": title}
        if raw.get("kb_name"):
            item["kb_name"] = str(raw["kb_name"])[:100]
        if raw.get("page") is not None:
            item["page"] = str(raw["page"])[:20] if not isinstance(raw["page"], int) else raw["page"]
        if content:
            item["content"] = content[:600]
        url = raw.get("url")
        if isinstance(url, str) and url.startswith(("https://", "http://")):
            item["url"] = url[:1000]
        key = (item["title"], item.get("page"), item.get("content"))
        if key not in seen:
            result.append(item)
            seen.add(key)
        if len(result) >= 12:
            break
    return result


class TutorBridge:
    def __init__(self, factory=DeepTutorApp, timeout_seconds=180):
        self._factory = factory
        self._timeout_seconds = timeout_seconds

    async def ask(self, text, *, session_id=None, capability="chat", knowledge_bases=None, difficulty=None, student_note=None):
        if not isinstance(text, str) or not text.strip():
            raise ValueError("请输入学习问题")
        if len(text) > 4000:
            raise ValueError("问题不能超过 4000 个字符")
        if capability not in {"chat", "deep_solve"}:
            raise ValueError("不支持的教学模式")
        if knowledge_bases is None:
            knowledge_bases = []
        if not isinstance(knowledge_bases, list) or not all(
            isinstance(name, str) and name.strip() for name in knowledge_bases
        ):
            raise ValueError("知识库列表格式错误")
        if difficulty is None and student_note and student_note.strip():
            raise ValueError("请先选择学习卡点")

        app = self._factory()
        request = {
            "content": build_learning_prompt(text.strip(), difficulty, student_note) if difficulty is not None else text.strip(),
            "capability": capability,
            "knowledge_bases": knowledge_bases,
            "language": "zh",
        }
        if session_id:
            request["session_id"] = session_id
        session, turn = await app.start_turn(request)
        answer = ""
        sources = []
        error = ""
        status = ""
        try:
            async with asyncio.timeout(self._timeout_seconds):
                async with aclosing(app.stream_turn(turn["id"])) as events:
                    async for event in events:
                        event_type = event.get("type")
                        metadata = event.get("metadata") or {}
                        if event_type == "sources":
                            raw_sources = metadata.get("sources")
                            if isinstance(raw_sources, list):
                                sources = visible_sources([*sources, *raw_sources])
                        if event_type == "tool_result":
                            tool_metadata = metadata.get("tool_metadata") or metadata
                            prompt = tool_metadata.get("ask_user") if isinstance(tool_metadata, dict) else None
                            if isinstance(prompt, dict) and prompt.get("kind") != "mastery_question":
                                questions = prompt.get("questions") or []
                                question = "；".join(
                                    item.get("prompt", "").strip()
                                    for item in questions
                                    if isinstance(item, dict) and isinstance(item.get("prompt"), str)
                                )
                                await app.cancel_turn(turn["id"])
                                return {
                                    "session_id": session["id"],
                                    "turn_id": turn["id"],
                                    "answer": question or "教学智能体需要你补充信息，请在输入框继续回答。",
                                    "sources": [],
                                    "speech_segments": [],
                                    "needs_input": True,
                                }
                        if event_type == "result":
                            response = metadata.get("response")
                            answer = response.strip() if isinstance(response, str) else ""
                            if not sources:
                                result_sources = metadata.get("sources")
                                sources = visible_sources(result_sources) if isinstance(result_sources, list) else []
                        elif event_type == "error":
                            error = str(event.get("content") or "教学智能体处理失败")
                        elif event_type == "done":
                            status = str(metadata.get("status") or "")
                            break
        except TimeoutError as exc:
            await app.cancel_turn(turn["id"])
            raise RuntimeError("教学智能体等待超时，请重试") from exc
        if status != "completed":
            raise RuntimeError(error or "教学智能体处理失败")
        if not answer:
            raise RuntimeError("教学智能体没有生成可播报的答案")
        return {
            "session_id": session["id"],
            "turn_id": turn["id"],
            "answer": answer,
            "sources": sources,
            "speech_segments": speech_segments(answer),
        }


bridge = TutorBridge()


@router.post("/ask")
async def ask(request: AskRequest):
    try:
        result = await bridge.ask(
            request.text,
            session_id=request.session_id,
            capability=request.capability,
            knowledge_bases=request.knowledge_bases,
            difficulty=request.difficulty,
            student_note=request.student_note,
        )
        return {"code": 0, "msg": "ok", "data": result}
    except ValueError as exc:
        return JSONResponse({"code": -1, "msg": str(exc)}, status_code=400)
    except RuntimeError as exc:
        return JSONResponse({"code": -1, "msg": str(exc)}, status_code=503)
