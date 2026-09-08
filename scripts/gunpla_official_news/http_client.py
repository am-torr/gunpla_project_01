"""Direct-HTTP transport plus a fixture transport that speaks the same protocol.

ARCHITECTURE.md section 2/7: fetching is direct HTTP with a browser User-Agent.
No ``web_search``, no Firecrawl.

Two implementations:

* :class:`UrllibTransport`  -- real network.
* :class:`FixtureTransport` -- serves a recorded source set from a manifest, and
  exposes the SAME ``opener`` seam that :mod:`images` uses for HTTP HEAD, so an
  end-to-end run against fixtures exercises the real verification code path rather
  than a stubbed-out one.

The ``opener`` seam is the important bit: :func:`images.head` takes a callable of
``urllib.request.Request -> context manager with .status/.headers``.  Both
transports provide one, so nothing in :mod:`images` needs a test-only branch.
"""
from __future__ import annotations

import json
import logging
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from .config import DEFAULT_HEADERS, DEFAULT_TIMEOUT

log = logging.getLogger(__name__)


@dataclass
class Response:
    url: str
    status: Optional[int] = None
    content_type: str = ""
    text: str = ""
    error: str = ""

    @property
    def ok(self) -> bool:
        return self.status == 200


class _FakeHTTPResponse:
    """Minimal stand-in for ``http.client.HTTPResponse`` (context manager)."""

    def __init__(self, status: int, headers: dict, body: bytes = b"") -> None:
        self.status = int(status)
        self.headers = dict(headers)
        self._body = body

    def getcode(self) -> int:
        return self.status

    def read(self) -> bytes:
        return self._body

    def __enter__(self) -> "_FakeHTTPResponse":
        return self

    def __exit__(self, *exc) -> bool:
        return False


class UrllibTransport:
    """Direct HTTP over urllib with a browser User-Agent."""

    def __init__(self, timeout: int = DEFAULT_TIMEOUT) -> None:
        self.timeout = timeout

    def get(self, url: str) -> Response:
        request = urllib.request.Request(url, headers=dict(DEFAULT_HEADERS))
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as resp:
                raw = resp.read()
                headers = getattr(resp, "headers", {}) or {}
                ctype = headers.get("Content-Type", "") if hasattr(headers, "get") else ""
                charset = "utf-8"
                if "charset=" in str(ctype):
                    charset = str(ctype).split("charset=", 1)[1].split(";")[0].strip()
                return Response(
                    url=url,
                    status=int(getattr(resp, "status", 0) or resp.getcode()),
                    content_type=str(ctype),
                    text=raw.decode(charset, errors="replace"),
                )
        except urllib.error.HTTPError as exc:
            return Response(url=url, status=int(exc.code), error=str(exc))
        except Exception as exc:  # noqa: BLE001 - a dead source is not a crash
            log.warning("GET %s failed: %s", url, exc)
            return Response(url=url, error=str(exc))

    @property
    def opener(self):
        def _open(request: urllib.request.Request):
            return urllib.request.urlopen(request, timeout=self.timeout)

        return _open


@dataclass
class FixtureTransport:
    """Serve a recorded source set described by ``manifest.json``.

    Manifest shape::

        {
          "https://example.com/news/": {"file": "news_index.html"},
          "https://example.com/media/a.jpg": {"content_type": "image/jpeg"},
          "https://www.reddit.com/r/Gunpla/search.json?q=x": {"status": 403}
        }

    Defaults: ``status`` 200, ``content_type`` ``text/html; charset=utf-8``.  An
    unlisted URL yields status 404 (GET) / raises HTTPError 404 (HEAD), which is
    what a real missing page does.
    """

    root: Path
    manifest: dict = field(default_factory=dict)
    requests_made: list = field(default_factory=list)

    @classmethod
    def from_dir(cls, root, manifest_name: str = "manifest.json") -> "FixtureTransport":
        root = Path(root)
        with open(root / manifest_name, "r", encoding="utf-8") as fh:
            manifest = json.load(fh)
        return cls(root=root, manifest=manifest)

    # -- helpers ------------------------------------------------------------
    def _entry(self, url: str) -> Optional[dict]:
        entry = self.manifest.get(url)
        return dict(entry) if isinstance(entry, dict) else None

    def _body(self, entry: dict) -> str:
        name = entry.get("file")
        if not name:
            return entry.get("body", "")
        with open(self.root / name, "r", encoding="utf-8") as fh:
            return fh.read()

    # -- transport protocol -------------------------------------------------
    def get(self, url: str) -> Response:
        self.requests_made.append(("GET", url))
        entry = self._entry(url)
        if entry is None:
            return Response(url=url, status=404, error="not in fixture manifest")
        status = int(entry.get("status", 200))
        ctype = entry.get("content_type", "text/html; charset=utf-8")
        if status != 200:
            return Response(url=url, status=status, content_type=ctype, error="fixture status")
        return Response(url=url, status=status, content_type=ctype, text=self._body(entry))

    @property
    def opener(self):
        def _open(request: urllib.request.Request):
            url = request.full_url
            self.requests_made.append((request.get_method(), url))
            entry = self._entry(url)
            if entry is None:
                raise urllib.error.HTTPError(url, 404, "not in fixture manifest", {}, None)
            status = int(entry.get("status", 200))
            ctype = entry.get("content_type", "text/html; charset=utf-8")
            if status >= 400:
                raise urllib.error.HTTPError(url, status, "fixture status", {}, None)
            return _FakeHTTPResponse(status, {"Content-Type": ctype})

        return _open
