"""AC5 -- n8n pusher: exact payload shape, headers, fail-soft behaviour.

No real network call is made anywhere in this file. ``push_to_n8n`` takes an
injectable ``urlopen`` seam (mirroring the ``opener`` pattern already used by
:mod:`images` / :mod:`http_client`), so tests supply a fake that records the
request and returns a canned response -- the same style batch 0 already
established for HTTP-touching code in this package.
"""
from __future__ import annotations

import json
import urllib.error
import urllib.request

import pytest

from gunpla_official_news import n8n_push as N


# ---------------------------------------------------------------------------
# Fakes
# ---------------------------------------------------------------------------


class FakeResponse:
    def __init__(self, status: int = 200) -> None:
        self.status = status

    def getcode(self) -> int:
        return self.status

    def __enter__(self) -> "FakeResponse":
        return self

    def __exit__(self, *exc) -> bool:
        return False


def make_recording_urlopen(status: int = 200):
    """Return (urlopen, calls) -- calls records each Request object seen."""
    calls: list = []

    def _urlopen(request, timeout=None):
        calls.append((request, timeout))
        return FakeResponse(status)

    return _urlopen, calls


def make_raising_urlopen(exc: BaseException):
    def _urlopen(request, timeout=None):
        raise exc

    return _urlopen


def _headers_ci(request: urllib.request.Request) -> dict:
    """Case-insensitive header view -- urllib.Request.capitalize()s header
    names internally (``X-Hermes-Secret`` -> ``X-hermes-secret``), so tests
    must not assert on the literal casing to avoid pinning that quirk."""
    return {k.lower(): v for k, v in request.header_items()}


BRIEF_TEXT = "# Gunpla News Brief\n\nSome verified content.\n"
WORKING_DATA = [{"kit_item": "HG Test Kit", "confidence": "High"}]
JOB_ID = "gunpla-news-2026-09-06"
RUN_AT = "2026-09-06T09:00:00+08:00"


# ---------------------------------------------------------------------------
# build_payload -- the exact 4-key shape
# ---------------------------------------------------------------------------


def test_build_payload_is_the_exact_four_key_shape():
    payload = N.build_payload(BRIEF_TEXT, WORKING_DATA, JOB_ID, RUN_AT)
    assert payload == {
        "brief_text": BRIEF_TEXT,
        "working_data": WORKING_DATA,
        "job_id": JOB_ID,
        "run_at": RUN_AT,
    }
    assert list(payload.keys()) == ["brief_text", "working_data", "job_id", "run_at"]


# ---------------------------------------------------------------------------
# push_to_n8n -- happy path: method, headers, body, url
# ---------------------------------------------------------------------------


def test_push_delivers_post_with_identical_payload_and_headers():
    urlopen, calls = make_recording_urlopen(status=200)
    rc = N.push_to_n8n(
        BRIEF_TEXT,
        WORKING_DATA,
        JOB_ID,
        RUN_AT,
        webhook_url="http://localhost:5679/webhook/hermes-gunpla-news",
        webhook_secret="topsecret",
        urlopen=urlopen,
    )
    assert rc == 0
    assert len(calls) == 1
    request, timeout = calls[0]

    assert request.full_url == "http://localhost:5679/webhook/hermes-gunpla-news"
    assert request.get_method() == "POST"
    assert timeout == N.DEFAULT_TIMEOUT

    headers = _headers_ci(request)
    assert headers["content-type"] == "application/json"
    assert headers["x-hermes-secret"] == "topsecret"

    body = json.loads(request.data.decode("utf-8"))
    assert body == {
        "brief_text": BRIEF_TEXT,
        "working_data": WORKING_DATA,
        "job_id": JOB_ID,
        "run_at": RUN_AT,
    }


def test_push_prints_delivered_status_on_success(capsys):
    urlopen, _ = make_recording_urlopen(status=200)
    N.push_to_n8n(
        BRIEF_TEXT, WORKING_DATA, JOB_ID, RUN_AT,
        webhook_url="http://x/webhook", webhook_secret="s", urlopen=urlopen,
    )
    out = capsys.readouterr().out
    assert "delivered" in out
    assert "200" in out


# ---------------------------------------------------------------------------
# Fail-soft: missing config
# ---------------------------------------------------------------------------


def test_missing_both_env_vars_skips_and_never_calls_urlopen(monkeypatch, capsys):
    monkeypatch.delenv(N.ENV_WEBHOOK_URL, raising=False)
    monkeypatch.delenv(N.ENV_WEBHOOK_SECRET, raising=False)
    urlopen, calls = make_recording_urlopen()

    rc = N.push_to_n8n(BRIEF_TEXT, WORKING_DATA, JOB_ID, RUN_AT, urlopen=urlopen)

    assert rc == 0
    assert calls == []
    assert "skipping" in capsys.readouterr().err


def test_missing_secret_only_skips(monkeypatch):
    monkeypatch.setenv(N.ENV_WEBHOOK_URL, "http://x/webhook")
    monkeypatch.delenv(N.ENV_WEBHOOK_SECRET, raising=False)
    urlopen, calls = make_recording_urlopen()

    rc = N.push_to_n8n(BRIEF_TEXT, WORKING_DATA, JOB_ID, RUN_AT, urlopen=urlopen)

    assert rc == 0
    assert calls == []


def test_missing_url_only_skips(monkeypatch):
    monkeypatch.delenv(N.ENV_WEBHOOK_URL, raising=False)
    monkeypatch.setenv(N.ENV_WEBHOOK_SECRET, "s")
    urlopen, calls = make_recording_urlopen()

    rc = N.push_to_n8n(BRIEF_TEXT, WORKING_DATA, JOB_ID, RUN_AT, urlopen=urlopen)

    assert rc == 0
    assert calls == []


def test_env_vars_are_read_when_kwargs_not_supplied(monkeypatch):
    monkeypatch.setenv(N.ENV_WEBHOOK_URL, "http://env-configured/webhook")
    monkeypatch.setenv(N.ENV_WEBHOOK_SECRET, "env-secret")
    urlopen, calls = make_recording_urlopen()

    rc = N.push_to_n8n(BRIEF_TEXT, WORKING_DATA, JOB_ID, RUN_AT, urlopen=urlopen)

    assert rc == 0
    assert len(calls) == 1
    request, _ = calls[0]
    assert request.full_url == "http://env-configured/webhook"
    assert _headers_ci(request)["x-hermes-secret"] == "env-secret"


# ---------------------------------------------------------------------------
# Fail-soft: network / HTTP errors -- never raise, never return non-zero
# ---------------------------------------------------------------------------


def test_connection_failure_fails_soft(capsys):
    urlopen = make_raising_urlopen(urllib.error.URLError("connection refused"))
    rc = N.push_to_n8n(
        BRIEF_TEXT, WORKING_DATA, JOB_ID, RUN_AT,
        webhook_url="http://dead-host/webhook", webhook_secret="s", urlopen=urlopen,
    )
    assert rc == 0
    err = capsys.readouterr().err
    assert "delivery failed" in err
    assert "Discord delivery is unaffected" in err


def test_http_error_status_fails_soft(capsys):
    http_error = urllib.error.HTTPError("http://x/webhook", 500, "Internal Server Error", {}, None)
    urlopen = make_raising_urlopen(http_error)
    rc = N.push_to_n8n(
        BRIEF_TEXT, WORKING_DATA, JOB_ID, RUN_AT,
        webhook_url="http://x/webhook", webhook_secret="s", urlopen=urlopen,
    )
    assert rc == 0
    assert "delivery failed" in capsys.readouterr().err


def test_unexpected_exception_during_delivery_fails_soft(capsys):
    """A bug or an exotic error (not a URLError) must still never raise."""
    urlopen = make_raising_urlopen(TimeoutError("timed out"))
    rc = N.push_to_n8n(
        BRIEF_TEXT, WORKING_DATA, JOB_ID, RUN_AT,
        webhook_url="http://x/webhook", webhook_secret="s", urlopen=urlopen,
    )
    assert rc == 0
    assert "skipping" in capsys.readouterr().err


def test_unencodable_working_data_fails_soft(capsys):
    urlopen, calls = make_recording_urlopen()
    rc = N.push_to_n8n(
        BRIEF_TEXT,
        {"bad": {1, 2, 3}},  # a set is not JSON-serializable
        JOB_ID,
        RUN_AT,
        webhook_url="http://x/webhook",
        webhook_secret="s",
        urlopen=urlopen,
    )
    assert rc == 0
    assert calls == [], "must not attempt delivery once payload encoding fails"
    assert "skipping" in capsys.readouterr().err


# ---------------------------------------------------------------------------
# push_report -- reads a RunReport-shaped object's output files and pushes
# ---------------------------------------------------------------------------


class _FakeReport:
    def __init__(self, outputs: dict) -> None:
        self.outputs = outputs


def test_push_report_reads_outputs_and_pushes(tmp_path):
    brief_path = tmp_path / "verified_brief_2026-09-06.md"
    json_path = tmp_path / "working_data_2026-09-06.json"
    with open(brief_path, "w", encoding="utf-8") as fh:
        fh.write(BRIEF_TEXT)
    with open(json_path, "w", encoding="utf-8") as fh:
        json.dump(WORKING_DATA, fh)

    report = _FakeReport({"verified_brief": brief_path, "working_data_json": json_path})
    urlopen, calls = make_recording_urlopen()

    rc = N.push_report(
        report,
        job_id=JOB_ID,
        run_at=RUN_AT,
        webhook_url="http://x/webhook",
        webhook_secret="s",
        urlopen=urlopen,
    )

    assert rc == 0
    assert len(calls) == 1
    request, _ = calls[0]
    body = json.loads(request.data.decode("utf-8"))
    assert body["brief_text"] == BRIEF_TEXT
    assert body["working_data"] == WORKING_DATA
    assert body["job_id"] == JOB_ID
    assert body["run_at"] == RUN_AT


def test_push_report_missing_output_file_fails_soft(tmp_path, capsys):
    report = _FakeReport(
        {
            "verified_brief": tmp_path / "does-not-exist.md",
            "working_data_json": tmp_path / "also-missing.json",
        }
    )
    urlopen, calls = make_recording_urlopen()

    rc = N.push_report(report, job_id=JOB_ID, run_at=RUN_AT, urlopen=urlopen)

    assert rc == 0
    assert calls == []
    assert "failed to read pipeline outputs" in capsys.readouterr().err


def test_push_report_reads_non_ascii_content_as_utf8(tmp_path):
    """This box's console is cp1252 -- prove the read path is UTF-8, not locale."""
    brief_path = tmp_path / "brief.md"
    json_path = tmp_path / "data.json"
    non_ascii_brief = "# ガンプラ News — 2026-09-06\n"
    with open(brief_path, "w", encoding="utf-8") as fh:
        fh.write(non_ascii_brief)
    with open(json_path, "w", encoding="utf-8") as fh:
        json.dump([{"kit_item": "ガンダム"}], fh, ensure_ascii=False)

    report = _FakeReport({"verified_brief": brief_path, "working_data_json": json_path})
    urlopen, calls = make_recording_urlopen()

    rc = N.push_report(
        report, job_id=JOB_ID, run_at=RUN_AT,
        webhook_url="http://x/webhook", webhook_secret="s", urlopen=urlopen,
    )

    assert rc == 0
    body = json.loads(calls[0][0].data.decode("utf-8"))
    assert body["brief_text"] == non_ascii_brief
    assert body["working_data"] == [{"kit_item": "ガンダム"}]


# ---------------------------------------------------------------------------
# CLI (main) -- parity with post_to_n8n.py's argument surface
# ---------------------------------------------------------------------------


def test_cli_skip_path_never_touches_the_network(tmp_path, monkeypatch, capsys):
    monkeypatch.delenv(N.ENV_WEBHOOK_URL, raising=False)
    monkeypatch.delenv(N.ENV_WEBHOOK_SECRET, raising=False)

    brief_path = tmp_path / "brief.md"
    data_path = tmp_path / "data.json"
    with open(brief_path, "w", encoding="utf-8") as fh:
        fh.write(BRIEF_TEXT)
    with open(data_path, "w", encoding="utf-8") as fh:
        json.dump(WORKING_DATA, fh)

    rc = N.main(
        [
            "--brief-file", str(brief_path),
            "--data-file", str(data_path),
            "--job-id", JOB_ID,
            "--run-at", RUN_AT,
        ]
    )

    assert rc == 0
    assert "skipping" in capsys.readouterr().err


def test_cli_reads_input_files_and_reports_bad_input_softly(tmp_path, capsys):
    rc = N.main(
        [
            "--brief-file", str(tmp_path / "missing-brief.md"),
            "--data-file", str(tmp_path / "missing-data.json"),
            "--job-id", JOB_ID,
            "--run-at", RUN_AT,
        ]
    )
    assert rc == 0
    assert "failed to read input" in capsys.readouterr().err
