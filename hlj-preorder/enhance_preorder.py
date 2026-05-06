from pathlib import Path

candidates = [
    Path(__file__).resolve().parent / "scripts" / "hlj_preorder_tracker.py",
    Path(__file__).resolve().parent / "hlj_preorder_tracker.py",
]

for target in candidates:
    if target.exists():
        break
else:
    raise FileNotFoundError("Could not find hlj_preorder_tracker.py")

text = target.read_text(encoding="utf-8")

old = '''                    badge_text = ""
                    if sku != "Unknown":
                        badge_div = card.select_one(f"div#{sku}_stock > div")
                        badge_text = badge_div.get_text(strip=True) if badge_div else ""
                    if not badge_text:
                        d = card.select_one(f"div#{sku}_stockStatusDetail")
                        badge_text = d.get_text(strip=True) if d else ""
'''
new = '''                    badge_text = ""
                    if sku != "Unknown":
                        stock_box = card.select_one(f"#{sku}_stock")
                        badge_text = stock_box.get_text(" ", strip=True) if stock_box else ""
                    if not badge_text:
                        d = card.select_one(f"div#{sku}_stockStatusDetail")
                        badge_text = d.get_text(" ", strip=True) if d else ""
'''

text = text.replace(old, new)
target.write_text(text, encoding="utf-8")
print("patched badge extraction")
print("\n".join(text.splitlines()[90:115]))