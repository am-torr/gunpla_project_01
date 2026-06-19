"""Link shortening — mirrors the live `02` chain: Bitly -> TinyURL -> raw affiliate.

Best-effort: every step swallows errors and falls through. Returns the original
affiliate URL if shortening is disabled or all providers fail.
"""
import httpx

from .config import settings


async def shorten(affiliate_url: str) -> str:
    if not settings.ENABLE_SHORTENER or not affiliate_url:
        return affiliate_url

    async with httpx.AsyncClient(timeout=15.0) as client:
        # 1) Bitly (only if a token is configured)
        token = settings.BITLY_ACCESS_TOKEN
        if token:
            auth = token if token.lower().startswith("bearer ") else f"Bearer {token}"
            try:
                r = await client.post(
                    "https://api-ssl.bitly.com/v4/shorten",
                    headers={"Authorization": auth, "Content-Type": "application/json"},
                    json={"long_url": affiliate_url},
                )
                if r.status_code in (200, 201):
                    link = r.json().get("link")
                    if link:
                        return link
            except Exception as exc:
                print(f"  WARN shorten/bitly: {exc}")

        # 2) TinyURL fallback
        try:
            r = await client.get(
                "https://tinyurl.com/api-create.php", params={"url": affiliate_url}
            )
            if r.status_code == 200 and r.text.strip().startswith("http"):
                return r.text.strip()
        except Exception as exc:
            print(f"  WARN shorten/tinyurl: {exc}")

    # 3) Raw affiliate URL
    return affiliate_url
