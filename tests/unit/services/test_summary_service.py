from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from app.modules.aims.services import summary_service as svc


@pytest.mark.asyncio
async def test_build_summary_returns_empty_analysis_when_requested_without_session():
    result = await svc.build_summary(
        session_id=None,
        analysis=True,
        memory_store={},
        memory_enabled=True,
        settings=SimpleNamespace(),
        logger=MagicMock(),
        app_state=SimpleNamespace(),
        vertex_client_cls=object(),
    )

    assert result["analysis"] == []


@pytest.mark.asyncio
async def test_build_summary_recovers_from_analysis_failure(monkeypatch):
    async def explode(**kwargs):
        raise RuntimeError("analysis failed")

    monkeypatch.setattr(svc, "_analysis_bullets", explode)

    result = await svc.build_summary(
        session_id="sid",
        analysis=True,
        memory_store={"sid": {"aims": {"perStepCounts": {}, "scores": {}}}},
        memory_enabled=True,
        settings=SimpleNamespace(),
        logger=MagicMock(),
        app_state=SimpleNamespace(),
        vertex_client_cls=object(),
    )

    assert result["analysis"] == []


def test_running_average_ignores_bad_score_lists():
    running = svc._running_average({"scores": {"Announce": ["bad"]}})

    assert running == {}


def test_load_mapping_returns_cached_app_state_mapping():
    cached = {"Announce": ["rule"]}
    app_state = SimpleNamespace(aims_mapping=cached)

    assert svc._load_mapping(app_state) is cached


def test_load_mapping_returns_empty_dict_when_loader_fails(monkeypatch):
    app_state = SimpleNamespace()

    monkeypatch.setattr("app.modules.aims.engine.load_mapping", MagicMock(side_effect=RuntimeError("boom")))

    assert svc._load_mapping(app_state) == {}


@pytest.mark.asyncio
async def test_build_summary_analysis_bullets_falls_back_when_sanitizer_fails(monkeypatch):
    monkeypatch.setattr(
        "app.services.vertex_helpers.vertex_call_with_fallback_text",
        lambda *args, **kwargs: "- First bullet\n- Second bullet",
    )
    monkeypatch.setattr(
        "app.services.coach_post.sanitize_endgame_bullets",
        MagicMock(side_effect=RuntimeError("sanitize failed")),
    )
    monkeypatch.setattr(
        svc,
        "_load_mapping",
        lambda app_state: {"Announce": ["rule"]},
    )

    bullets = await svc.build_summary_analysis_bullets(
        mem={"history": [{"role": "user", "content": "hello"}], "aims": {"perStepCounts": {}, "runningAverage": {}}},
        settings=SimpleNamespace(
            PROJECT_ID="proj",
            VERTEX_LOCATION="global",
            MODEL_ID="gemini-test",
            MODEL_FALLBACKS=[],
            TEMPERATURE=0.2,
            MAX_TOKENS=256,
        ),
        logger=MagicMock(),
        app_state=SimpleNamespace(),
        vertex_client_cls=object(),
    )

    assert bullets == ["First bullet", "Second bullet"]
