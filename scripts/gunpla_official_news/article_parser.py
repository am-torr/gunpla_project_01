"""Level-2 extraction: article HTML -> a structured candidate.

ARCHITECTURE.md section 2 lists what must come out of each article: ``title``,
``datePublished``, ``seriesTags[]``, ``categories[]``, ``summary/description``, and
``body content`` (for images and detailed kit info).

Extraction is stdlib-only (``html.parser`` + regex) so the module has no hard
dependency on bs4/lxml and can run in a bare test environment.  Structured meta
tags win over body heuristics whenever both are present -- a page that states its
own price is more trustworthy than a regex over prose.
"""
from __future__ import annotations

import html as html_module
import json
import re
from dataclasses import dataclass, field
from html.parser import HTMLParser
from typing import Optional

#: Meta names/properties consulted for the published date, in priority order.
_DATE_META_KEYS = (
    "datepublished",
    "article:published_time",
    "og:published_time",
    "pubdate",
)

#: Yen signs as escapes (U+00A5 YEN SIGN, U+FFE5 FULLWIDTH YEN SIGN) so this
#: source file stays pure ASCII while still matching real Japanese price strings.
_YEN_SIGNS = "\u00a5\uffe5"
_PRICE_RE = re.compile(
    "(?:[" + _YEN_SIGNS + r"]|JPY\s*)\s*([\d,]+)|([\d,]+)\s*(?:yen|JPY)",
    re.IGNORECASE,
)
_RELEASE_RE = re.compile(
    r"(?:release(?:\s+date)?|on sale|ships?)\s*[:\-]?\s*"
    r"([A-Z][a-z]+\s+\d{4}|\d{4}-\d{2}(?:-\d{2})?|Q[1-4]\s+\d{4})",
    re.IGNORECASE,
)
_GRADE_RE = re.compile(r"\b(MGEX|MGSD|PG|MG|RG|HGUC|HGCE|HG|EG|SD|FM|RE/100)\b")

_EXCLUSIVITY_KEYWORDS = (
    ("premium bandai", "Premium"),
    ("p-bandai", "Premium"),
    ("event exclusive", "Event"),
    ("event-limited", "Event"),
    ("gundam base", "Event"),
    ("general retail", "Retail"),
    ("retail release", "Retail"),
)

_GRADE_TYPE_KEYWORDS = (
    ("event", "Event"),
    ("figure", "Figure"),
    ("apparel", "Apparel"),
    ("goods", "Goods"),
    ("anime", "Media"),
    ("film", "Media"),
)


class _Extractor(HTMLParser):
    """Collect title, meta tags, image srcs and visible text in one pass."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.title = ""
        self.metas: dict = {}
        self.images: list = []
        self._text: list = []
        self._in_title = False
        self._skip_depth = 0

    def handle_starttag(self, tag, attrs):
        attrd = {k.lower(): (v or "") for k, v in attrs}
        if tag == "title":
            self._in_title = True
        elif tag in ("script", "style"):
            self._skip_depth += 1
        elif tag == "meta":
            key = (attrd.get("name") or attrd.get("property") or "").strip().lower()
            if key:
                self.metas[key] = attrd.get("content", "").strip()
        elif tag == "img":
            src = attrd.get("src", "").strip()
            if src:
                self.images.append(src)
        elif tag == "time":
            dt = attrd.get("datetime", "").strip()
            if dt and "datetime" not in self.metas:
                self.metas["datetime"] = dt

    def handle_endtag(self, tag):
        if tag == "title":
            self._in_title = False
        elif tag in ("script", "style") and self._skip_depth:
            self._skip_depth -= 1

    def handle_data(self, data):
        if self._in_title:
            self.title += data
        elif not self._skip_depth:
            stripped = data.strip()
            if stripped:
                self._text.append(stripped)

    @property
    def text(self) -> str:
        return "\n".join(self._text)


@dataclass
class Article:
    """One parsed source page."""

    url: str = ""
    title: str = ""
    date_published: str = ""
    series_tags: list = field(default_factory=list)
    categories: list = field(default_factory=list)
    summary: str = ""
    body_text: str = ""
    body_html: str = ""
    image_urls: list = field(default_factory=list)
    metas: dict = field(default_factory=dict)

    # -- extracted kit facts ------------------------------------------------
    grade_type: str = ""
    release: str = ""
    msrp: str = ""
    exclusivity: str = ""

    def meta_flag(self, key: str, default: bool = False) -> bool:
        """Read a boolean-ish meta tag (fixtures and real schema.org both use these)."""
        raw = self.metas.get(key.lower())
        if raw is None:
            return default
        return str(raw).strip().lower() in ("true", "1", "yes")

    def meta(self, key: str, default: str = "") -> str:
        return self.metas.get(key.lower(), default) or default


def _split_list(value: str) -> list:
    return [p.strip() for p in re.split(r"[,;|]", value) if p.strip()]


def _extract_release(article_text: str) -> str:
    m = _RELEASE_RE.search(article_text)
    return m.group(1).strip() if m else ""


def _extract_msrp(article_text: str) -> str:
    m = _PRICE_RE.search(article_text)
    if not m:
        return ""
    amount = m.group(1) or m.group(2)
    return "%s yen" % amount if amount else ""


def _extract_exclusivity(article_text: str) -> str:
    low = article_text.lower()
    for needle, label in _EXCLUSIVITY_KEYWORDS:
        if needle in low:
            return label
    return ""


def _extract_grade_type(title: str, article_text: str, categories: list) -> str:
    blob = " ".join([title, " ".join(categories)]).lower()
    for needle, label in _GRADE_TYPE_KEYWORDS:
        if needle in blob:
            return label
    if _GRADE_RE.search(title) or _GRADE_RE.search(article_text):
        return "Kit"
    return ""


#: Matches one `self.__next_f.push([N,"..."])` React Server Components chunk.
#: The second array element is itself a JSON-escaped string (standard JSON
#: string-body grammar: any char but quote/backslash, or backslash-escape).
_NEXT_F_PUSH_RE = re.compile(r'self\.__next_f\.push\(\[\d+,\s*"((?:[^"\\]|\\.)*)"\]\)')


def _find_balanced_object(text: str, key: str) -> Optional[str]:
    """Return the ``{...}`` object following ``"key":`` in ``text``, brace-balanced."""
    idx = text.find('"' + key + '":')
    if idx < 0:
        return None
    start = text.find("{", idx)
    if start < 0:
        return None
    depth = 0
    in_str = False
    esc = False
    for i in range(start, len(text)):
        c = text[i]
        if in_str:
            if esc:
                esc = False
            elif c == "\\":
                esc = True
            elif c == '"':
                in_str = False
            continue
        if c == '"':
            in_str = True
        elif c == "{":
            depth += 1
        elif c == "}":
            depth -= 1
            if depth == 0:
                return text[start : i + 1]
    return None


def extract_nextjs_news_response(html: str) -> Optional[dict]:
    """Pull a Next.js flight-payload ``newsResponse`` object out of a page.

    Sites built on Next.js App Router (e.g. en.gundam-official.com) render no
    server-side ``<a href>``/``<meta>`` tags at all -- every field lives inside
    one of several ``self.__next_f.push([N,"<escaped-json>"])`` chunks. Each
    chunk's string argument is itself valid JSON-string-escaped text, so it
    unescapes with a single ``json.loads('"' + body + '"')`` pass; the
    ``newsResponse`` object inside that unescaped text is then plain JSON.
    Returns ``None`` (never raises) if the page isn't this shape.
    """
    for body in _NEXT_F_PUSH_RE.findall(html or ""):
        if "newsResponse" not in body:
            continue
        try:
            unescaped = json.loads('"' + body + '"')
        except (json.JSONDecodeError, ValueError):
            continue
        blob = _find_balanced_object(unescaped, "newsResponse")
        if not blob:
            continue
        try:
            return json.loads(blob)
        except json.JSONDecodeError:
            continue
    return None


def parse_article(html: str, url: str = "") -> Article:
    """Parse one article page into an :class:`Article`."""
    parser = _Extractor()
    parser.feed(html or "")
    parser.close()

    metas = parser.metas
    title = html_module.unescape(parser.title).strip() or metas.get("og:title", "")

    date_published = ""
    for key in _DATE_META_KEYS:
        if metas.get(key):
            date_published = metas[key].strip()
            break
    if not date_published:
        date_published = metas.get("datetime", "").strip()
    # Normalise "2026-09-02T10:00:00Z" -> keep full string; sorting is lexicographic.

    series_tags = _split_list(metas.get("seriestags", "") or metas.get("series", ""))
    categories = _split_list(metas.get("categories", "") or metas.get("category", ""))
    summary = metas.get("description", "") or metas.get("og:description", "")

    text = parser.text
    article = Article(
        url=url,
        title=title,
        date_published=date_published,
        series_tags=series_tags,
        categories=categories,
        summary=summary,
        body_text=text,
        body_html=html or "",
        image_urls=list(parser.images),
        metas=metas,
    )
    article.release = metas.get("release", "") or _extract_release(text)
    article.msrp = metas.get("msrp", "") or _extract_msrp(text)
    article.exclusivity = metas.get("exclusivity", "") or _extract_exclusivity(text)
    article.grade_type = metas.get("grade_type", "") or _extract_grade_type(
        title, text, categories
    )

    # Fallback for Next.js flight-payload pages: no <title>/<meta> tags were
    # emitted server-side, so nothing above found anything. Try the embedded
    # newsResponse blob instead (see extract_nextjs_news_response).
    if not article.title and "self.__next_f.push(" in (html or ""):
        blob = extract_nextjs_news_response(html)
        if blob:
            article.title = blob.get("title") or article.title
            article.date_published = blob.get("displayDatetime") or article.date_published
            article.summary = blob.get("summary") or article.summary
            if not article.series_tags:
                article.series_tags = [
                    s.get("name", "") for s in (blob.get("seriesTags") or []) if s.get("name")
                ]
            if not article.categories:
                article.categories = [
                    c.get("name", "") for c in (blob.get("categories") or []) if c.get("name")
                ]
            thumb_url = (blob.get("thumbnail") or {}).get("url")
            if thumb_url and thumb_url not in article.image_urls:
                article.image_urls.append(thumb_url)

            fallback_text = " ".join([article.title, article.summary])
            article.release = article.release or _extract_release(fallback_text)
            article.msrp = article.msrp or _extract_msrp(fallback_text)
            article.exclusivity = article.exclusivity or _extract_exclusivity(fallback_text)
            article.grade_type = article.grade_type or _extract_grade_type(
                article.title, fallback_text, article.categories
            )
    return article


_LINK_RE = re.compile(r"""<a\b[^>]*\bhref\s*=\s*["']([^"']+)["']""", re.IGNORECASE)
#: Bare absolute URLs appearing as plain text (not inside a tag) -- the shape
#: they take in a Next.js flight payload, e.g. `"url":"https://host/news/x"`.
_ABS_URL_RE = re.compile(r"""https?://[^\s"'<>\\]+""")


def extract_article_links(
    html: str, *, prefix: Optional[str] = None, fallback_prefix: Optional[str] = None
) -> list:
    """Pull article URLs out of a listing page, in document order, de-duplicated.

    ``fallback_prefix`` only kicks in when zero ``<a href>`` tags are found at
    all -- some listing pages (Next.js App Router sites) render none server-side,
    but still embed the real article URLs as plain escaped text elsewhere on the
    page. When given, it scopes that fallback scan to URLs starting with it
    (normally the listing URL itself) so unrelated same-page URLs (CDN assets,
    analytics beacons) aren't picked up.
    """
    out: list = []
    seen: set = set()
    for match in _LINK_RE.finditer(html or ""):
        href = html_module.unescape(match.group(1)).strip()
        if not href.lower().startswith(("http://", "https://")):
            continue
        if prefix and not href.startswith(prefix):
            continue
        if href in seen:
            continue
        seen.add(href)
        out.append(href)

    if out or not fallback_prefix:
        return out

    for match in _ABS_URL_RE.finditer(html or ""):
        href = html_module.unescape(match.group(0)).rstrip(").,;\\\"'")
        if not href.startswith(fallback_prefix) or href == fallback_prefix:
            continue
        if href in seen:
            continue
        seen.add(href)
        out.append(href)
    return out
