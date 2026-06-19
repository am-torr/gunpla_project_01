"""Draft review UI — a small, mobile-friendly front door over `agent_drafts`.

The human reviewer sees each draft (image, classification, production post_copy,
optional LLM caption, deal/dedup signals) and approves or rejects it. Approving
sets status='approved'; the n8n side is untouched. Runs as the `lowstock-review`
container (uvicorn) on REVIEW_PORT.

    uvicorn scripts.lowstock_agent.review_app:app --host 0.0.0.0 --port 8011
"""
import html
from datetime import datetime, timezone

from fastapi import FastAPI
from fastapi.responses import HTMLResponse, JSONResponse

from .config import get_supabase

app = FastAPI(title="Low-stock Draft Review")


def _fetch(status: str = "draft", limit: int = 100) -> list[dict]:
    sb = get_supabase()
    res = (
        sb.table("agent_drafts")
        .select("*")
        .eq("status", status)
        .order("qualified", desc=True)
        .order("created_at", desc=True)
        .limit(limit)
        .execute()
    )
    return res.data or []


def _counts() -> dict:
    sb = get_supabase()
    out = {}
    for s in ("draft", "approved", "rejected"):
        r = sb.table("agent_drafts").select("id", count="exact").eq("status", s).execute()
        out[s] = r.count or 0
    return out


def _badge(label: str, value, kind: str = "") -> str:
    if value in (None, "", False):
        return ""
    return f'<span class="badge {kind}">{html.escape(str(label))}: {html.escape(str(value))}</span>'


def _card(d: dict) -> str:
    e = html.escape
    imgs = d.get("image_urls") or []
    img = e(imgs[0]) if imgs else ""
    img_html = f'<img src="{img}" alt="" loading="lazy">' if img else '<div class="noimg">no image</div>'
    qualified = d.get("qualified")
    q_badge = (
        '<span class="badge ok">QUALIFIED</span>' if qualified
        else f'<span class="badge muted">skip · {e(d.get("gate_reason") or "")}</span>'
    )
    badges = "".join([
        _badge("grade", d.get("grade_normalized")),
        _badge("scale", d.get("scale_ai")),
        _badge("type", d.get("product_type_ai")),
        _badge("brand", d.get("brand_ai")),
        _badge("conf", d.get("classification_confidence")),
        _badge("stock", d.get("stock_urgency"), "warn"),
        _badge("deal", d.get("deal_signal")),
        _badge("posted_recently", d.get("posted_recently"), "warn") if d.get("posted_recently") else "",
    ])
    post_copy = e(d.get("post_copy") or "")
    caption = d.get("suggested_caption")
    caption_html = (
        f'<div class="cap"><div class="lbl">suggested caption ({e(d.get("caption_tone") or "")})</div>'
        f'<div>{e(caption)}</div></div>' if caption else ""
    )
    tags = d.get("suggested_hashtags") or []
    tags_html = f'<div class="tags">{e(" ".join(tags))}</div>' if tags else ""
    link = d.get("short_link") or d.get("affiliate_url") or ""
    link_html = f'<a href="{e(link)}" target="_blank" rel="noopener">{e(link)}</a>' if link else ""
    did = e(d.get("id"))
    return f"""
    <div class="card" id="card-{did}">
      <div class="media">{img_html}</div>
      <div class="body">
        <div class="row1">{q_badge}<span class="sku">{e(d.get("sku") or "")}</span></div>
        <h3>{e(d.get("name") or "")}</h3>
        <div class="badges">{badges}</div>
        <pre class="postcopy">{post_copy}</pre>
        {caption_html}
        {tags_html}
        <div class="link">{link_html}</div>
        <div class="actions">
          <button class="approve" onclick="act('{did}','approve')">Approve</button>
          <button class="reject" onclick="act('{did}','reject')">Reject</button>
        </div>
      </div>
    </div>"""


PAGE = """<!doctype html><html lang="en"><head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>Low-stock Draft Review</title>
<style>
:root {{ color-scheme: light dark; }}
* {{ box-sizing: border-box; }}
body {{ margin:0; font-family: system-ui, -apple-system, Segoe UI, Roboto, sans-serif;
  background:#0f1115; color:#e7e9ee; }}
header {{ position:sticky; top:0; background:#161922; padding:14px 16px; border-bottom:1px solid #262b38;
  display:flex; gap:12px; align-items:center; flex-wrap:wrap; }}
header h1 {{ font-size:16px; margin:0; }}
.pill {{ font-size:12px; background:#222838; border:1px solid #2f3850; padding:3px 9px; border-radius:999px; }}
.wrap {{ max-width:760px; margin:0 auto; padding:16px; display:flex; flex-direction:column; gap:14px; }}
.card {{ background:#161922; border:1px solid #262b38; border-radius:14px; overflow:hidden; display:flex; }}
.media {{ width:120px; min-width:120px; background:#0c0e13; display:flex; align-items:center; justify-content:center; }}
.media img {{ width:100%; height:100%; object-fit:cover; }}
.noimg {{ color:#566; font-size:12px; padding:8px; text-align:center; }}
.body {{ padding:12px 14px; flex:1; min-width:0; }}
.row1 {{ display:flex; gap:8px; align-items:center; margin-bottom:4px; }}
.sku {{ color:#8b93a7; font-size:12px; font-family:ui-monospace,monospace; }}
h3 {{ font-size:15px; margin:2px 0 8px; line-height:1.3; }}
.badges {{ display:flex; flex-wrap:wrap; gap:6px; margin-bottom:8px; }}
.badge {{ font-size:11px; background:#1d2230; border:1px solid #2c3346; color:#aeb6c8; padding:2px 7px; border-radius:6px; }}
.badge.ok {{ background:#10331f; border-color:#1c5e36; color:#5fe08c; }}
.badge.warn {{ background:#3a2a12; border-color:#6b4c1c; color:#f0c068; }}
.badge.muted {{ background:#23262f; color:#8b93a7; }}
.postcopy {{ white-space:pre-wrap; font-family:ui-monospace,monospace; font-size:12.5px;
  background:#0c0e13; border:1px solid #232838; border-radius:8px; padding:9px; margin:0 0 8px; overflow-x:auto; }}
.cap {{ font-size:13px; background:#12161f; border-left:3px solid #3a64c0; padding:8px 10px; border-radius:6px; margin-bottom:8px; }}
.cap .lbl {{ font-size:10.5px; text-transform:uppercase; letter-spacing:.05em; color:#7f8aa3; margin-bottom:3px; }}
.tags {{ font-size:12px; color:#7fa0e0; margin-bottom:8px; }}
.link a {{ font-size:12px; color:#6fb0ff; word-break:break-all; }}
.actions {{ display:flex; gap:10px; margin-top:10px; }}
button {{ flex:1; padding:10px; border:0; border-radius:9px; font-weight:600; font-size:14px; cursor:pointer; }}
.approve {{ background:#1c7a3f; color:#fff; }}
.reject {{ background:#3a2030; color:#ff9aa6; border:1px solid #6b2a3c; }}
.empty {{ text-align:center; color:#7f8aa3; padding:60px 16px; }}
.card.gone {{ opacity:.35; pointer-events:none; }}
@media (max-width:520px) {{ .media {{ width:92px; min-width:92px; }} }}
</style></head><body>
<header><h1>🪖 Low-stock Draft Review</h1>
  <span class="pill">draft: {n_draft}</span>
  <span class="pill">approved: {n_approved}</span>
  <span class="pill">rejected: {n_rejected}</span>
</header>
<div class="wrap">{cards}</div>
<script>
async function act(id, action) {{
  const card = document.getElementById('card-'+id);
  card.classList.add('gone');
  try {{
    const r = await fetch('/drafts/'+id+'/'+action, {{method:'POST'}});
    if (!r.ok) throw new Error(await r.text());
    setTimeout(() => card.remove(), 200);
  }} catch (e) {{ card.classList.remove('gone'); alert('Failed: '+e); }}
}}
</script></body></html>"""


@app.get("/", response_class=HTMLResponse)
def index() -> str:
    drafts = _fetch("draft")
    counts = _counts()
    cards = "".join(_card(d) for d in drafts) or '<div class="empty">No drafts to review. 🎉</div>'
    return PAGE.format(
        cards=cards,
        n_draft=counts.get("draft", 0),
        n_approved=counts.get("approved", 0),
        n_rejected=counts.get("rejected", 0),
    )


@app.post("/drafts/{draft_id}/{action}")
def act(draft_id: str, action: str):
    if action not in ("approve", "reject"):
        return JSONResponse({"error": "bad action"}, status_code=400)
    status = "approved" if action == "approve" else "rejected"
    sb = get_supabase()
    sb.table("agent_drafts").update(
        {"status": status, "updated_at": datetime.now(timezone.utc).isoformat()}
    ).eq("id", draft_id).execute()
    return JSONResponse({"id": draft_id, "status": status})


@app.get("/health")
def health():
    return {"status": "ok"}
