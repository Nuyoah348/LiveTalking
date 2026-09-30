from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]


def _load_script_module(name: str):
    path = ROOT / "scripts" / "model_services" / f"{name}.py"
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_embedding_input_normalization_preserves_openai_order():
    module = _load_script_module("embedding_server")

    assert module.normalize_inputs("one") == ["one"]
    assert module.normalize_inputs(["one", "two"]) == ["one", "two"]

    with pytest.raises(ValueError, match="non-empty string"):
        module.normalize_inputs([])
    with pytest.raises(ValueError, match="non-empty string"):
        module.normalize_inputs(["ok", ""])


def test_sensevoice_text_cleanup_removes_event_tags():
    module = _load_script_module("sensevoice_server")

    assert module.clean_transcript("<|zh|><|NEUTRAL|><|Speech|>你好，老师。") == "你好，老师。"
    assert module.clean_transcript("plain text") == "plain text"


def test_cloud_startup_contract_uses_one_public_port_and_internal_services():
    start = (ROOT / "scripts" / "start_platform.sh").read_text(encoding="utf-8")
    status = (ROOT / "scripts" / "status_platform.sh").read_text(encoding="utf-8")
    stop = (ROOT / "scripts" / "stop_platform.sh").read_text(encoding="utf-8")

    assert 'DEEPTUTOR_WEB_PORT="${DEEPTUTOR_WEB_PORT:-6006}"' in start
    assert "-H 0.0.0.0" in start
    assert "--port 8000" in start
    assert "--gpu-memory-utilization" in start
    assert "embedding_server:app" in start
    assert "sensevoice_server:app" in start
    assert "--port 8001" in start
    assert "--listenport 8010" in start
    assert "DEEPTUTOR_API_BASE_URL" in start
    assert "DIGITAL_HUMAN_API_BASE_URL" in start
    assert "status_platform.sh" in start
    assert '"$PID_DIR/$name.pid"' in status
    assert '"$PID_DIR/$name.pid"' in stop
