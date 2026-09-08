"""AC6 -- native APScheduler-style runner; no Hermes-side changes.

Mirrors ``scripts/lowstock_agent/scheduler.py``'s shape (AsyncIOScheduler,
interval tick, overlap guard, structured logging). ``run_once`` is a coroutine;
each test drives it directly with ``asyncio.run`` rather than pulling in
pytest-asyncio for one coroutine per test.

``load_config`` is a pure function of an explicit mapping, so env-var parsing
is tested without mutating real process environment variables or reload()-ing
the module.
"""
from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from gunpla_official_news import scheduler as S


class _FakeReport:
    def __init__(self):
        self.articles = 3
        self.rows = 2
        self.outputs = {"verified_brief": "b.md", "working_data_json": "d.json"}


@pytest.fixture(autouse=True)
def _reset_running_guard():
    """Every test starts with a clean overlap guard, regardless of test order."""
    S._running = False
    yield
    S._running = False


# ---------------------------------------------------------------------------
# load_config -- pure function of an explicit env mapping
# ---------------------------------------------------------------------------


def test_load_config_defaults_when_env_is_empty():
    cfg = S.load_config({})
    assert cfg.interval_hours == 24.0
    assert cfg.run_on_start is False
    assert cfg.output_dir == Path("output")
    assert cfg.use_fixtures is False


@pytest.mark.parametrize("truthy", ["1", "true", "True", "YES", "yes"])
def test_load_config_recognizes_true_strings(truthy):
    cfg = S.load_config(
        {"GUNPLA_NEWS_RUN_ON_START": truthy, "GUNPLA_NEWS_USE_FIXTURES": truthy}
    )
    assert cfg.run_on_start is True
    assert cfg.use_fixtures is True


def test_load_config_recognizes_false_strings():
    cfg = S.load_config(
        {"GUNPLA_NEWS_RUN_ON_START": "false", "GUNPLA_NEWS_USE_FIXTURES": "0"}
    )
    assert cfg.run_on_start is False
    assert cfg.use_fixtures is False


def test_load_config_overrides_from_env():
    cfg = S.load_config(
        {
            "GUNPLA_NEWS_RUN_INTERVAL_HOURS": "6",
            "GUNPLA_NEWS_RUN_ON_START": "true",
            "GUNPLA_NEWS_OUTPUT_DIR": "custom_out",
            "GUNPLA_NEWS_USE_FIXTURES": "yes",
        }
    )
    assert cfg.interval_hours == 6.0
    assert cfg.run_on_start is True
    assert cfg.output_dir == Path("custom_out")
    assert cfg.use_fixtures is True


def test_module_level_constants_match_default_config():
    """The module's own constants are produced by load_config(), not re-derived."""
    assert S.RUN_INTERVAL_HOURS == S.CONFIG.interval_hours
    assert S.RUN_ON_START == S.CONFIG.run_on_start
    assert S.OUTPUT_DIR == S.CONFIG.output_dir
    assert S.USE_FIXTURES == S.CONFIG.use_fixtures


# ---------------------------------------------------------------------------
# run_once -- the tick: pipeline -> push, overlap guard, exception isolation
# ---------------------------------------------------------------------------


def test_run_once_runs_fixtures_pipeline_then_pushes(monkeypatch):
    calls = []

    def fake_run_fixtures(*, output_dir, date):
        calls.append(("run_fixtures", output_dir, date))
        return _FakeReport()

    def fake_run(*, output_dir, date):
        calls.append(("run", output_dir, date))
        return _FakeReport()

    def fake_push_report(report, *, job_id, run_at):
        calls.append(("push_report", report, job_id, run_at))
        return 0

    monkeypatch.setattr(S.pipeline, "run_fixtures", fake_run_fixtures)
    monkeypatch.setattr(S.pipeline, "run", fake_run)
    monkeypatch.setattr(S.n8n_push, "push_report", fake_push_report)
    monkeypatch.setattr(S, "USE_FIXTURES", True)

    asyncio.run(S.run_once())

    names = [c[0] for c in calls]
    assert names == ["run_fixtures", "push_report"]
    _, report, job_id, run_at = calls[1]
    assert isinstance(report, _FakeReport)
    assert job_id.startswith("gunpla-news-")
    assert len(job_id) == len("gunpla-news-") + 12
    assert run_at  # a non-empty ISO timestamp was generated


def test_run_once_uses_live_run_when_fixtures_disabled(monkeypatch):
    calls = []
    monkeypatch.setattr(
        S.pipeline, "run", lambda **kw: calls.append(("run", kw)) or _FakeReport()
    )
    monkeypatch.setattr(
        S.pipeline,
        "run_fixtures",
        lambda **kw: calls.append(("run_fixtures", kw)) or _FakeReport(),
    )
    monkeypatch.setattr(S.n8n_push, "push_report", lambda *a, **kw: 0)
    monkeypatch.setattr(S, "USE_FIXTURES", False)

    asyncio.run(S.run_once())

    assert [c[0] for c in calls] == ["run"]


def test_run_once_passes_configured_output_dir_and_today(monkeypatch):
    seen = {}

    def fake_run_fixtures(*, output_dir, date):
        seen["output_dir"] = output_dir
        seen["date"] = date
        return _FakeReport()

    monkeypatch.setattr(S.pipeline, "run_fixtures", fake_run_fixtures)
    monkeypatch.setattr(S.n8n_push, "push_report", lambda *a, **kw: 0)
    monkeypatch.setattr(S, "USE_FIXTURES", True)
    monkeypatch.setattr(S, "OUTPUT_DIR", Path("my_output"))

    asyncio.run(S.run_once())

    assert seen["output_dir"] == Path("my_output")
    # YYYY-MM-DD
    assert len(seen["date"]) == 10 and seen["date"][4] == "-" and seen["date"][7] == "-"


def test_run_once_skips_when_a_previous_tick_is_still_running(monkeypatch):
    calls = []
    monkeypatch.setattr(
        S.pipeline, "run_fixtures", lambda **kw: calls.append("run") or _FakeReport()
    )
    monkeypatch.setattr(
        S.n8n_push, "push_report", lambda *a, **kw: calls.append("push") or 0
    )
    monkeypatch.setattr(S, "USE_FIXTURES", True)
    S._running = True  # simulate an in-flight tick

    asyncio.run(S.run_once())

    assert calls == [], "an overlapping tick must never touch the pipeline or n8n_push"


def test_running_guard_releases_after_a_successful_tick(monkeypatch):
    monkeypatch.setattr(S.pipeline, "run_fixtures", lambda **kw: _FakeReport())
    monkeypatch.setattr(S.n8n_push, "push_report", lambda *a, **kw: 0)
    monkeypatch.setattr(S, "USE_FIXTURES", True)

    asyncio.run(S.run_once())

    assert S._running is False


def test_pipeline_exception_is_caught_never_raised_and_guard_still_releases(monkeypatch):
    def boom(**kw):
        raise RuntimeError("pipeline exploded")

    push_calls = []
    monkeypatch.setattr(S.pipeline, "run_fixtures", boom)
    monkeypatch.setattr(
        S.n8n_push, "push_report", lambda *a, **kw: push_calls.append(1) or 0
    )
    monkeypatch.setattr(S, "USE_FIXTURES", True)

    asyncio.run(S.run_once())  # must not raise

    assert push_calls == [], "a failed pipeline run must never reach the push step"
    assert S._running is False


def test_push_report_failure_cannot_escape_run_once(monkeypatch):
    """n8n_push is fail-soft by its own contract, but prove the tick survives
    even a defect that violates that contract (belt and suspenders)."""
    monkeypatch.setattr(S.pipeline, "run_fixtures", lambda **kw: _FakeReport())

    def broken_push(*a, **kw):
        raise RuntimeError("push_report violated its fail-soft contract")

    monkeypatch.setattr(S.n8n_push, "push_report", broken_push)
    monkeypatch.setattr(S, "USE_FIXTURES", True)

    asyncio.run(S.run_once())  # must not raise

    assert S._running is False


# ---------------------------------------------------------------------------
# No Hermes-side changes (AC6): this module never imports/touches the Hermes
# skill path or scripts/lowstock_agent's own scheduler.
# ---------------------------------------------------------------------------


def test_scheduler_module_never_imports_lowstock_or_hermes_paths():
    import ast
    import pathlib

    path = pathlib.Path(S.__file__).resolve()
    with open(path, "r", encoding="utf-8") as fh:
        tree = ast.parse(fh.read(), filename=str(path))

    banned = {"lowstock_agent", "hermes"}
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                assert not any(b in alias.name.lower() for b in banned), alias.name
        elif isinstance(node, ast.ImportFrom):
            module = (node.module or "").lower()
            assert not any(b in module for b in banned), module


def test_scheduler_uses_asyncio_scheduler_matching_the_lowstock_pattern():
    import inspect

    source = inspect.getsource(S.main)
    assert "AsyncIOScheduler" in source
    assert '"interval"' in source
    assert "max_instances=1" in source
    assert "coalesce=True" in source
