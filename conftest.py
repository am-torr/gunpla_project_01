"""Pytest bootstrap: put the workspace root and scripts/ on sys.path.

Mirrors how the real project is run:
  * `scripts/` on sys.path -> `import gunpla_official_news`
    (config.SOURCES uses top-level `gunpla_official_news.sources.*` paths)
  * workspace root on sys.path -> `import scripts.lowstock_agent`, `import app.hlj_helpers`
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
SCRIPTS = ROOT / "scripts"

for p in (str(ROOT), str(SCRIPTS)):
    if p not in sys.path:
        sys.path.insert(0, p)
