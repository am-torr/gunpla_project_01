"""Push the pipeline's Verified Brief + Working Data to n8n (AC5).

Ports ``post_to_n8n.py`` (the Hermes ``gunpla-news-gatherer`` skill,
``C:\\Users\\amtor\\AppData\\Local\\hermes\\skills\\productivity\\gunpla-news-gatherer\\
scripts\\post_to_n8n.py`` -- read-only reference, never edited by this project)
EXACT payload contract into this package, so this pipeline's own scheduler
(``scheduler.py``) can call the existing "Hermes News Webhook Ingest" n8n
webhook directly. Nothing on the Hermes side changes: same env var names, same
payload shape, same header, same fail-soft behaviour.

Payload (byte-identical shape to ``post_to_n8n.py``)::

    {"brief_text": ..., "working_data": ..., "job_id": ..., "run_at": ...}

Method POST, ``Content-Type: application/json``, header ``X-Hermes-Secret``.

Env vars (same names ``post_to_n8n.py`` already reads -- one shared secret
config powers both delivery paths)::

    N8N_WEBHOOK_URL      full webhook URL
    N8N_WEBHOOK_SECRET   shared secret sent as X-Hermes-Secret

FAIL-SOFT CONTRACT (mirrors ``post_to_n8n.py`` exactly): this module must
NEVER raise and NEVER signal failure to its caller. A missing env var, a
payload that will not JSON-encode, a DNS failure, a connection refusal, or a
non-2xx HTTP response are all logged to stderr and swallowed. A webhook outage
must never fail the pipeline run or scheduler tick that pushes to it -- Discord
delivery (Hermes' existing path) is completely unaffected either way.
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Callable, Optional, Sequence

log = logging.getLogger(__name__)

#: Same env var names post_to_n8n.py reads.
ENV_WEBHOOK_URL = "N8N_WEBHOOK_URL"
ENV_WEBHOOK_SECRET = "N8N_WEBHOOK_SECRET"
HEADER_SECRET_NAME = "X-Hermes-Secret"
DEFAULT_TIMEOUT = 10


def build_payload(brief_text: str, working_data: Any, job_id: str, run_at: str) -> dict:
    """The exact 4-key shape ``post_to_n8n.py`` sends."""
    return {
        "brief_text": brief_text,
        "working_data": working_data,
        "job_id": job_id,
        "run_at": run_at,
    }


def push_to_n8n(
    brief_text: str,
    working_data: Any,
    job_id: str,
    run_at: str,
    *,
    webhook_url: Optional[str] = None,
    webhook_secret: Optional[str] = None,
    timeout: int = DEFAULT_TIMEOUT,
    urlopen: Callable = urllib.request.urlopen,
) -> int:
    """POST the payload to the n8n webhook. Never raises; always returns 0.

    ``urlopen`` is an injectable seam for tests -- mirrors the ``opener``
    pattern already used by :mod:`images` / :mod:`http_client`. Production
    callers leave it as ``urllib.request.urlopen``.
    """
    webhook_url = os.environ.get(ENV_WEBHOOK_URL) if webhook_url is None else webhook_url
    webhook_secret = (
        os.environ.get(ENV_WEBHOOK_SECRET) if webhook_secret is None else webhook_secret
    )

    if not webhook_url or not webhook_secret:
        print(
            "n8n_push: N8N_WEBHOOK_URL / N8N_WEBHOOK_SECRET not set, skipping",
            file=sys.stderr,
        )
        return 0

    try:
        payload = build_payload(brief_text, working_data, job_id, run_at)
        body = json.dumps(payload).encode("utf-8")
    except (TypeError, ValueError) as exc:
        print(f"n8n_push: failed to encode payload, skipping: {exc}", file=sys.stderr)
        return 0

    request = urllib.request.Request(
        webhook_url,
        data=body,
        method="POST",
        headers={
            "Content-Type": "application/json",
            HEADER_SECRET_NAME: webhook_secret,
        },
    )

    try:
        with urlopen(request, timeout=timeout) as resp:
            status = getattr(resp, "status", None) or resp.getcode()
            print(f"n8n_push: delivered, status={status}")
    except urllib.error.URLError as exc:
        print(
            f"n8n_push: delivery failed, skipping (Discord delivery is unaffected): {exc}",
            file=sys.stderr,
        )
    except Exception as exc:  # noqa: BLE001 - a webhook outage must never fail the caller
        log.warning("n8n_push: unexpected error, skipping: %s", exc)
        print(f"n8n_push: unexpected error, skipping: {exc}", file=sys.stderr)

    return 0


def push_report(report: Any, *, job_id: str, run_at: str, **kwargs: Any) -> int:
    """Read a completed pipeline run's brief + working-data.json and push them.

    ``report`` is a :class:`pipeline.RunReport` (or anything exposing an
    ``.outputs`` dict with ``verified_brief`` / ``working_data_json`` paths --
    exactly what ``pipeline.run()`` / ``pipeline.run_fixtures()`` return).
    Fail-soft like :func:`push_to_n8n`: a missing or unreadable output file is
    logged to stderr and swallowed rather than raised, so a scheduler tick that
    just wrote good output files can never be failed by this step.
    """
    try:
        brief_path = Path(report.outputs["verified_brief"])
        json_path = Path(report.outputs["working_data_json"])
        with open(brief_path, "r", encoding="utf-8") as fh:
            brief_text = fh.read()
        with open(json_path, "r", encoding="utf-8") as fh:
            working_data = json.load(fh)
    except Exception as exc:  # noqa: BLE001 - reading just-written outputs must not crash the run
        print(f"n8n_push: failed to read pipeline outputs, skipping: {exc}", file=sys.stderr)
        return 0

    return push_to_n8n(brief_text, working_data, job_id, run_at, **kwargs)


def _read_text(path: str) -> str:
    if path == "-":
        return sys.stdin.read()
    with open(path, "r", encoding="utf-8") as fh:
        return fh.read()


def main(argv: Optional[Sequence[str]] = None) -> int:
    """CLI parity with ``post_to_n8n.py``, for drop-in / manual use::

        python -m gunpla_official_news.n8n_push --brief-file b.md --data-file d.json \\
            --job-id gunpla-news-2026-09-06 --run-at 2026-09-06T09:00:00+08:00
    """
    parser = argparse.ArgumentParser(description=main.__doc__)
    parser.add_argument(
        "--brief-file", required=True, help="Verified Brief .md path, or - for stdin"
    )
    parser.add_argument("--data-file", required=True, help="working_data_<date>.json path")
    parser.add_argument("--job-id", required=True)
    parser.add_argument("--run-at", required=True, help="ISO 8601 timestamp of this run")
    args = parser.parse_args(list(argv) if argv is not None else None)

    try:
        brief_text = _read_text(args.brief_file)
        with open(args.data_file, "r", encoding="utf-8") as fh:
            working_data = json.load(fh)
    except Exception as exc:  # noqa: BLE001 - fail soft even reading CLI inputs
        print(f"n8n_push: failed to read input, skipping: {exc}", file=sys.stderr)
        return 0

    return push_to_n8n(brief_text, working_data, args.job_id, args.run_at)


if __name__ == "__main__":
    raise SystemExit(main())
