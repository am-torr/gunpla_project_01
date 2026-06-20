"""Official-domain allowlist check."""
from __future__ import annotations

from urllib.parse import urlparse

from .config import OFFICIAL_DOMAINS


def is_official_url(url: str) -> bool:
    if not url:
        return False
    try:
        host = (urlparse(url).hostname or "").lower()
    except ValueError:
        return False
    if not host:
        return False
    return any(host == d or host.endswith("." + d) for d in OFFICIAL_DOMAINS)
