"""Optional LLM "suggested caption" (enhancement over the deterministic post_copy).

Pattern source: the caption-generator skill — rotating tones + hashtags. This is
NOT what production posts (production uses the deterministic template in
postcopy.py); it is an extra suggestion surfaced to the human reviewer.

Returns a Caption: {caption, hashtags, tone}.
"""
import hashlib
from typing import Optional

from pydantic import BaseModel

from claude_agent_sdk import ClaudeAgentOptions, ResultMessage, query

from .. import config

TONES = ["urgent", "fan", "value", "hype", "neutral"]


class Caption(BaseModel):
    caption: str
    hashtags: list[str]


def select_tone(item: dict) -> str:
    """Urgent when only 1 left; otherwise rotate deterministically by SKU."""
    stock = item.get("stock") or ""
    if "only 1 " in stock.lower() or " 1 left" in stock.lower():
        return "urgent"
    sku = item.get("sku") or ""
    idx = int(hashlib.md5(sku.encode()).hexdigest(), 16) % len(TONES)
    return TONES[idx]


SYSTEM_PROMPT = (
    "You are a copywriter for the MEGALLANICA Gunpla deals page (Southeast Asian "
    "buyers). Write a short, engaging Facebook caption for a LOW-STOCK Gunpla deal "
    "and 3-6 hashtags. Buyers care about price-vs-Japan-retail, stock urgency, and "
    "the grade/series. Match the requested tone. Keep it PG. Do not invent a price "
    "or URL — those are added separately."
)

TONE_HINT = {
    "urgent": "Focus on scarcity; make them feel they'll miss out.",
    "fan": "Lean into Gundam lore; a line fans will recognize.",
    "value": "Lead with value/price positioning.",
    "hype": "Short, punchy — for iconic kits.",
    "neutral": "Clean and informative, no hype.",
}


async def write_caption(item: dict, classification) -> tuple[Optional[Caption], str]:
    tone = select_tone(item)
    prompt = (
        f"Tone: {tone} — {TONE_HINT.get(tone, '')}\n"
        f"name: {item.get('name')}\n"
        f"grade: {classification.grade_normalized}\n"
        f"scale: {classification.scale_ai}\n"
        f"stock: {item.get('stock')}\n"
    )

    options = ClaudeAgentOptions(
        system_prompt=SYSTEM_PROMPT,
        model=config.settings.CAPTION_MODEL,
        allowed_tools=[],
        setting_sources=[],
        max_turns=4,
        output_format={"type": "json_schema", "schema": Caption.model_json_schema()},
        env={"ANTHROPIC_API_KEY": config.settings.ANTHROPIC_API_KEY},
    )

    structured = None
    try:
        async for message in query(prompt=prompt, options=options):
            if isinstance(message, ResultMessage):
                if message.subtype == "success" and message.structured_output:
                    structured = message.structured_output
    except Exception as exc:
        print(f"  WARN caption({item.get('sku')}): {exc}")

    if structured:
        return Caption.model_validate(structured), tone
    return None, tone
