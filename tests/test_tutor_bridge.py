import asyncio
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "education"))
from deeptutor.api.routers.digital_human import TutorBridge, speech_segments


class FakeTutorApp:
    def __init__(self, events):
        self.events = events
        self.requests = []
        self.cancelled = []

    async def start_turn(self, request):
        self.requests.append(request)
        return {"id": "education-session"}, {"id": "turn-1"}

    async def stream_turn(self, turn_id):
        for event in self.events:
            yield event

    async def cancel_turn(self, turn_id):
        self.cancelled.append(turn_id)
        return True


def test_answer_uses_final_agent_result_and_preserves_session():
    app = FakeTutorApp([
        {"type": "content", "content": "正在检索资料"},
        {"type": "result", "metadata": {"response": "先理解分数的分母。", "sources": [{"title": "教材.pdf", "content": "分母表示平均分成的份数。"}]}},
        {"type": "done", "metadata": {"status": "completed"}},
    ])
    bridge = TutorBridge(factory=lambda: app)

    result = asyncio.run(bridge.ask("什么是分母？", session_id="previous", knowledge_bases=["math"]))

    assert result == {
        "session_id": "education-session",
        "turn_id": "turn-1",
        "answer": "先理解分数的分母。",
        "sources": [{"title": "教材.pdf", "content": "分母表示平均分成的份数。"}],
        "speech_segments": ["先理解分数的分母。"],
    }
    assert app.requests[0]["session_id"] == "previous"
    assert app.requests[0]["knowledge_bases"] == ["math"]
    assert app.requests[0]["language"] == "zh"


def test_failed_agent_turn_does_not_return_partial_text_for_speech():
    app = FakeTutorApp([
        {"type": "content", "content": "不完整的答案"},
        {"type": "error", "content": "模型服务不可用"},
        {"type": "done", "metadata": {"status": "failed"}},
    ])
    bridge = TutorBridge(factory=lambda: app)

    with pytest.raises(RuntimeError, match="模型服务不可用"):
        asyncio.run(bridge.ask("解释勾股定理"))


def test_empty_final_answer_is_an_error():
    app = FakeTutorApp([
        {"type": "result", "metadata": {"response": "  "}},
        {"type": "done", "metadata": {"status": "completed"}},
    ])
    bridge = TutorBridge(factory=lambda: app)

    with pytest.raises(RuntimeError, match="没有生成可播报的答案"):
        asyncio.run(bridge.ask("解释勾股定理"))


def test_speech_segments_split_sentences_and_long_text():
    result = speech_segments("第一步：读题。第二步：列式！" + "甲" * 170)

    assert result[:2] == ["第一步：读题。", "第二步：列式！"]
    assert "".join(result).endswith("甲" * 170)
    assert all(len(part) <= 120 for part in result)


def test_speech_segments_omit_common_markdown_marks_without_changing_math():
    assert speech_segments("## 分数\n**分母**表示份数。详见[教材](https://example.test/book)。3*4=12。") == [
        "分数\n分母表示份数。",
        "详见教材。",
        "3*4=12。",
    ]


def test_answer_returns_at_done_without_waiting_for_post_turn_metadata():
    class SlowTailTutorApp(FakeTutorApp):
        async def stream_turn(self, turn_id):
            yield {"type": "result", "metadata": {"response": "先列出已知条件。"}}
            yield {"type": "done", "metadata": {"status": "completed"}}
            await asyncio.sleep(1)

    bridge = TutorBridge(factory=lambda: SlowTailTutorApp([]))
    result = asyncio.run(asyncio.wait_for(bridge.ask("如何解题？"), timeout=0.1))

    assert result["answer"] == "先列出已知条件。"


def test_non_text_result_is_not_sent_to_speech():
    app = FakeTutorApp([
        {"type": "result", "metadata": {"response": {"text": "错误格式"}}},
        {"type": "done", "metadata": {"status": "completed"}},
    ])
    bridge = TutorBridge(factory=lambda: app)

    with pytest.raises(RuntimeError, match="没有生成可播报的答案"):
        asyncio.run(bridge.ask("解释勾股定理"))


def test_question_pause_returns_prompt_and_cancels_waiting_turn():
    app = FakeTutorApp([
        {"type": "tool_result", "metadata": {"tool_metadata": {
            "ask_user": {"questions": [{"prompt": "你目前学过方程吗？"}]}
        }}},
    ])
    result = asyncio.run(TutorBridge(factory=lambda: app).ask("讲解方程"))

    assert result["needs_input"] is True
    assert result["answer"] == "你目前学过方程吗？"
    assert result["speech_segments"] == []
    assert result["session_id"] == "education-session"
    assert app.cancelled == ["turn-1"]


def test_silent_turn_times_out_and_is_cancelled():
    class SilentTutorApp(FakeTutorApp):
        async def stream_turn(self, turn_id):
            await asyncio.sleep(1)
            yield {"type": "done", "metadata": {"status": "completed"}}

    app = SilentTutorApp([])
    with pytest.raises(RuntimeError, match="等待超时"):
        asyncio.run(TutorBridge(factory=lambda: app, timeout_seconds=0.01).ask("讲解方程"))
    assert app.cancelled == ["turn-1"]


def test_real_source_events_are_returned_without_query_only_echo():
    app = FakeTutorApp([
        {"type": "sources", "metadata": {"sources": [
            {"type": "rag", "query": "什么是分母", "kb_name": "数学"},
            {"type": "rag", "kb_name": "数学", "title": "七年级数学.pdf", "page": 12, "content": "分母表示平均分成的份数。"},
        ]}},
        {"type": "result", "metadata": {"response": "分母表示份数。"}},
        {"type": "done", "metadata": {"status": "completed"}},
    ])

    result = asyncio.run(TutorBridge(factory=lambda: app).ask("什么是分母？"))

    assert result["sources"] == [{
        "title": "七年级数学.pdf", "kb_name": "数学", "page": 12,
        "content": "分母表示平均分成的份数。",
    }]


def test_student_selected_difficulty_guides_turn_without_claiming_diagnosis():
    app = FakeTutorApp([
        {"type": "result", "metadata": {"response": "我们先看已知条件。"}},
        {"type": "done", "metadata": {"status": "completed"}},
    ])
    asyncio.run(TutorBridge(factory=lambda: app).ask(
        "这道方程怎么解？", difficulty="choose_method", student_note="我不会选方法"
    ))

    content = app.requests[0]["content"]
    assert "不知道用什么方法" in content
    assert "我不会选方法" in content
    assert "不代表已判定实际错因" in content


def test_student_note_without_selected_difficulty_is_rejected():
    app = FakeTutorApp([])
    with pytest.raises(ValueError, match="先选择学习卡点"):
        asyncio.run(TutorBridge(factory=lambda: app).ask("题目", student_note="卡住了"))
    assert app.requests == []
