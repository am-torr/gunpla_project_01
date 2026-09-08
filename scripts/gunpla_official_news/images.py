"""Image verification (ARCHITECTURE.md section 3 "Image handling" + section 6).

Three rules, all enforced here and nowhere else:

1. ``image_checked`` becomes True ONLY after a real HTTP HEAD returns ``200`` and a
   ``Content-Type`` of ``image/*``.  Nothing else may set it -- a URL that merely
   *looks* like an image is not verified.
2. Site-chrome filenames (``resized_Rectangle_*``) are excluded before any request
   is made; they are the source's own header/footer furniture, not article assets.
3. When the source page's footer carries the reproduction-prohibited notice, the
   item is flagged ``reuse_not_permitted``.  Verification proves the image EXISTS;
   it never proves we may republish it (ARCHITECTURE.md section 10).

The HEAD call is injectable: pass ``opener=`` a callable taking a
``urllib.request.Request`` and returning a context manager with ``.status`` and
``.headers``.  Tests use that seam; production uses urllib directly.  No
``web_search`` and no Firecrawl -- direct HTTP only (section 7).
"""
from __future__ import annotations

import logging
import re
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from typing import Callable, Iterable, Optional
from urllib.parse import urlparse

from .config import DEFAULT_HEADERS, DEFAULT_TIMEOUT

log = logging.getLogger(__name__)

#: Site chrome the article body links but that is not an article asset.
SITE_CHROME_PATTERNS: tuple[str, ...] = (r"resized_Rectangle_",)

_SITE_CHROME_RE = re.compile("|".join(SITE_CHROME_PATTERNS))

#: The footer notice that forbids redistribution.  Matched case-insensitively and
#: whitespace-insensitively so a re-flowed footer still trips it.
REUSE_PROHIBITED_NOTICE = "Reproduction of content and images is strictly prohibited."

_REUSE_NOTICE_RE = re.compile(
    r"reproduction\s+of\s+content\s+and\s+images\s+is\s+strictly\s+prohibited",
    re.IGNORECASE,
)

#: Metadata flag value used on the Working Data row.
REUSE_NOT_PERMITTED = "reuse_not_permitted"

#: Only these media hosts' paths are treated as article media by default.
ARTICLE_MEDIA_PATH_HINT = "/media/"


# ---------------------------------------------------------------------------
# Pure predicates
# ---------------------------------------------------------------------------


def is_site_chrome(url: str) -> bool:
    """True for ``resized_Rectangle_*`` style site furniture."""
    if not url:
        return False
    try:
        path = urlparse(url).path or url
    except ValueError:
        path = url
    filename = path.rsplit("/", 1)[-1]
    return bool(_SITE_CHROME_RE.search(filename))


def has_reuse_prohibited_notice(page_text: str) -> bool:
    """True when the page/footer carries the reproduction-prohibited notice."""
    if not page_text:
        return False
    return bool(_REUSE_NOTICE_RE.search(page_text))


def is_image_content_type(content_type: str) -> bool:
    """True for ``image/*`` (parameters such as ``; charset=`` are tolerated)."""
    if not content_type:
        return False
    return content_type.split(";", 1)[0].strip().lower().startswith("image/")


# ---------------------------------------------------------------------------
# HTTP HEAD
# ---------------------------------------------------------------------------


@dataclass
class HeadResult:
    url: str
    status: Optional[int] = None
    content_type: str = ""
    error: str = ""

    @property
    def ok(self) -> bool:
        return self.status == 200 and is_image_content_type(self.content_type)


Opener = Callable[[urllib.request.Request], object]


def _default_opener(request: urllib.request.Request):
    return urllib.request.urlopen(request, timeout=DEFAULT_TIMEOUT)


def _encode_url(url: str) -> str:
    """Percent-encode any raw non-ASCII bytes left in a URL's path/query.

    Some source pages embed image ``src`` values with literal, un-encoded
    non-ASCII characters (e.g. a Japanese folder name). ``http.client`` can only
    send an ASCII request line, so those raise ``UnicodeEncodeError`` before any
    request reaches the network. ``safe="/%"`` leaves already-percent-encoded
    sequences and path separators alone, so a normal URL round-trips unchanged.
    """
    parts = urllib.parse.urlsplit(url)
    path = urllib.parse.quote(parts.path, safe="/%")
    query = urllib.parse.quote(parts.query, safe="=&%")
    return urllib.parse.urlunsplit((parts.scheme, parts.netloc, path, query, parts.fragment))


def head(url: str, *, opener: Optional[Opener] = None) -> HeadResult:
    """Issue a real HTTP HEAD and report status + Content-Type.

    Never raises for network problems: a dead host is a failed verification, not a
    crashed pipeline.
    """
    opener = opener or _default_opener
    request = urllib.request.Request(
        _encode_url(url), method="HEAD", headers=dict(DEFAULT_HEADERS)
    )
    try:
        with opener(request) as response:  # type: ignore[attr-defined]
            status = getattr(response, "status", None)
            if status is None:  # older urllib response objects
                status = response.getcode()  # type: ignore[attr-defined]
            headers = getattr(response, "headers", {}) or {}
            content_type = ""
            if hasattr(headers, "get"):
                content_type = headers.get("Content-Type", "") or ""
            return HeadResult(url=url, status=int(status), content_type=str(content_type))
    except urllib.error.HTTPError as exc:  # 4xx/5xx still carry a status
        return HeadResult(url=url, status=int(exc.code), error=str(exc))
    except Exception as exc:  # noqa: BLE001 - degrade, never crash the run
        log.warning("HEAD %s failed: %s", url, exc)
        return HeadResult(url=url, error=str(exc))


def verify_image(url: str, *, opener: Optional[Opener] = None) -> bool:
    """True only for ``200`` + ``image/*``.  Site chrome is rejected without a request."""
    if is_site_chrome(url):
        return False
    return head(url, opener=opener).ok


# ---------------------------------------------------------------------------
# Batch verification
# ---------------------------------------------------------------------------


@dataclass
class ImageVerification:
    """Result of verifying one article's image set."""

    verified: list = field(default_factory=list)
    excluded_chrome: list = field(default_factory=list)
    failed: list = field(default_factory=list)
    reuse_not_permitted: bool = False

    @property
    def image_checked(self) -> bool:
        """True only when at least one URL passed a real HEAD verification."""
        return bool(self.verified)

    def top(self, n: int = 3) -> list:
        """First ``n`` verified URLs, padded with '' so slot mapping is stable."""
        out = list(self.verified[:n])
        while len(out) < n:
            out.append("")
        return out

    @property
    def flags(self) -> list:
        return [REUSE_NOT_PERMITTED] if self.reuse_not_permitted else []


def extract_image_urls(html: str, *, media_hint: str = ARTICLE_MEDIA_PATH_HINT) -> list:
    """Pull candidate image URLs out of article HTML, in document order.

    Site chrome is *not* filtered here -- ``verify_images`` records it separately so
    the exclusion stays visible in the run report instead of silently vanishing.
    """
    if not html:
        return []
    urls: list = []
    seen: set = set()
    for match in re.finditer(r"""(?:src|href|content)\s*=\s*["']([^"']+)["']""", html):
        url = match.group(1).strip()
        if not url.lower().startswith(("http://", "https://")):
            continue
        if media_hint and media_hint not in url:
            continue
        if url in seen:
            continue
        seen.add(url)
        urls.append(url)
    return urls


def verify_images(
    urls: Iterable[str],
    *,
    page_text: str = "",
    opener: Optional[Opener] = None,
) -> ImageVerification:
    """Verify every URL by HTTP HEAD and assess reuse permission.

    ``page_text`` is the source page (or just its footer); when it carries the
    reproduction-prohibited notice the result is flagged ``reuse_not_permitted``.
    """
    result = ImageVerification(
        reuse_not_permitted=has_reuse_prohibited_notice(page_text),
    )
    for url in urls:
        if not url:
            continue
        if is_site_chrome(url):
            result.excluded_chrome.append(url)
            continue
        head_result = head(url, opener=opener)
        if head_result.ok:
            result.verified.append(url)
        else:
            result.failed.append(url)
    return result
