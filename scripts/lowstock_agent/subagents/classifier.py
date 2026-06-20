"""Sub-agent 1 — classifier (LLM via Claude Agent SDK), batched.

Pattern source: the gunpla-classifier skill. Output mirrors the live
`post_queue_stg` AI columns so drafts line up with the production staging schema:
grade_normalized, scale_ai, product_type_ai, brand_ai, audience_ai,
classification_confidence (+ is_gunpla, ai_notes).

Funnel (per the skill — never classify one-by-one):
  1. Hard reject  — SKU prefix / keyword / price < threshold  (no LLM)
  2. Batched LLM  — everything else, in chunks of CLASSIFIER_BATCH_SIZE on Haiku
  3. Fallback     — deterministic heuristic if the batch call fails
"""
import re
from typing import Optional

from pydantic import BaseModel, Field

from claude_agent_sdk import ClaudeAgentOptions, ResultMessage, query

from .. import config
from ..parsing import extract_grade_scale, is_gunpla, sku_excluded

# Hard-reject keywords (from the gunpla-classifier skill) — never Gunpla kits.
HARD_REJECT_KEYWORDS = [
    "polycap", "panel line", "marker", "cement", "nippers", "magazine",
    "keychain", "figure rise", "figure-rise", "diorama", "base set",
    "top coat", "primer", "weathering", "catalogue", "catalog",
]
HARD_REJECT_PRICE_JPY = 200  # tools/consumables, not kits


class Classification(BaseModel):
    is_gunpla: bool
    grade_normalized: Optional[str] = None   # SD/HG/RG/MG/PG/EG/Unknown
    scale_ai: Optional[str] = None           # 1/144, 1/100, 1/60, non-scale, SD, Unknown
    product_type_ai: Optional[str] = None    # model_kit/figure/book/decal/apparel/merch
    brand_ai: Optional[str] = None           # Bandai/Kotobukiya/Megahouse/Other
    audience_ai: Optional[str] = None        # boys/girls/adult_collectors/unisex/unknown
    classification_confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    ai_notes: Optional[str] = None


class _BatchItem(Classification):
    sku: str


class _Batch(BaseModel):
    results: list[_BatchItem]


SYSTEM_PROMPT = (
    "You classify Hobby Link Japan (HLJ) products to enrich a Gunpla deals "
    "pipeline. For each product decide whether it is a genuine Gunpla / Gundam "
    "plastic model KIT and fill the staging fields:\n"
    "- is_gunpla: true only for buildable Bandai Gundam-line kits.\n"
    "- grade_normalized: SD, HG, RG, MG, PG, EG, or Unknown.\n"
    "- scale_ai: 1/144, 1/100, 1/60, non-scale, SD, or Unknown.\n"
    "- product_type_ai: model_kit, figure, book, decal, apparel, or merch.\n"
    "- brand_ai: Bandai, Kotobukiya, Megahouse, or Other.\n"
    "- audience_ai: boys, girls, adult_collectors, unisex, or unknown.\n"
    "- classification_confidence: 0.0-1.0.\n"
    "- ai_notes: short reason, especially when is_gunpla is false.\n"
    "Books, catalogs, magazines, paints, tools, decals, stands and figures are "
    "NOT gunpla kits. Echo each product's sku in your result."
)


def _hard_reject(item: dict) -> Optional[Classification]:
    name = (item.get("name") or "")
    name_lower = name.lower()
    sku = item.get("sku") or ""
    price = item.get("price_jpy")
    if isinstance(price, str):
        digits = re.sub(r"[^0-9.]", "", price)
        price = float(digits) if digits else None
    reasons = []
    if sku_excluded(sku):
        reasons.append("non-gunpla sku prefix")
    if any(kw in name_lower for kw in HARD_REJECT_KEYWORDS):
        reasons.append("hard-reject keyword")
    if isinstance(price, (int, float)) and price < HARD_REJECT_PRICE_JPY:
        reasons.append("price below kit threshold")
    if not reasons:
        return None
    return Classification(
        is_gunpla=False,
        grade_normalized=None, scale_ai=None,
        product_type_ai="merch", brand_ai="Other", audience_ai="unknown",
        classification_confidence=0.95,
        ai_notes="hard reject: " + ", ".join(reasons),
    )


def _heuristic(item: dict) -> Classification:
    name = item.get("name", "") or ""
    sku = item.get("sku", "") or ""
    gp = is_gunpla(name, sku)
    gs = extract_grade_scale(name)
    grade = None if gs == "Unknown" else gs.split()[0]
    scale_m = re.search(r"1/(\d+)", gs)
    return Classification(
        is_gunpla=gp,
        grade_normalized=grade,
        scale_ai=(f"1/{scale_m.group(1)}" if scale_m else None),
        product_type_ai="model_kit" if gp else "merch",
        brand_ai="Bandai" if gp else "Other",
        audience_ai="unknown",
        classification_confidence=0.40,
        ai_notes="heuristic fallback",
    )


async def _classify_chunk(items: list[dict]) -> dict:
    """One Haiku call for a chunk; returns {sku: Classification}."""
    lines = "\n".join(
        f"{i}. sku={it.get('sku')} | name={it.get('name')} | price_jpy={it.get('price_jpy')}"
        for i, it in enumerate(items)
    )
    prompt = "Classify each product. Return one result per product, echoing sku.\n\n" + lines

    options = ClaudeAgentOptions(
        system_prompt=SYSTEM_PROMPT,
        model=config.settings.CLASSIFIER_MODEL,
        allowed_tools=[],
        setting_sources=[],
        max_turns=4,
        output_format={"type": "json_schema", "schema": _Batch.model_json_schema()},
        env={"ANTHROPIC_API_KEY": config.settings.ANTHROPIC_API_KEY},
    )

    structured = None
    err = None
    try:
        async for message in query(prompt=prompt, options=options):
            if isinstance(message, ResultMessage):
                if getattr(message, "is_error", False):
                    err = message.result or "unknown error"        # e.g. "Credit balance is too low"
                elif message.subtype == "success" and message.structured_output:
                    structured = message.structured_output
    except Exception as exc:
        err = err or str(exc)
    if err and structured is None:
        print(f"  WARN classify batch: {err}")

    out: dict = {}
    if structured:
        for row in _Batch.model_validate(structured).results:
            out[row.sku] = Classification(**row.model_dump(exclude={"sku"}))
    # Fill any the model omitted with the heuristic
    for it in items:
        out.setdefault(it.get("sku"), _heuristic(it))
    return out


async def classify_items(items: list[dict]) -> dict:
    """Classify a whole batch. Returns {sku: Classification}."""
    results: dict = {}
    ambiguous: list[dict] = []

    for it in items:
        hard = _hard_reject(it)
        if hard is not None:
            results[it.get("sku")] = hard
        else:
            ambiguous.append(it)

    size = max(1, config.settings.CLASSIFIER_BATCH_SIZE)
    for start in range(0, len(ambiguous), size):
        chunk = ambiguous[start:start + size]
        results.update(await _classify_chunk(chunk))

    return results
