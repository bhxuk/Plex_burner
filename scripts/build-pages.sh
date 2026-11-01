#!/usr/bin/env bash
# Builds the GitHub Pages demo in docs/demo/ from the real app in app/static/,
# so the public demo always matches the dashboard. Run after changing anything
# in app/static/.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
"${PYTHON:-python3}" - "$ROOT" <<'PY'
import re, shutil, sys
from pathlib import Path

root = Path(sys.argv[1])
static, out = root / "app" / "static", root / "docs" / "demo"
version = (root / "app" / "VERSION").read_text().strip()

if out.exists():
    shutil.rmtree(out)
out.mkdir(parents=True)
shutil.copytree(static, out / "assets", ignore=shutil.ignore_patterns("index.html"))
demo = out / "assets" / "demo.js"
demo.write_text(re.sub(r'VERSION = "[^"]+"', f'VERSION = "{version}"', demo.read_text(encoding="utf-8"), count=1), encoding="utf-8")

inject = '<script>window.PB_DEMO = true;</script>\n<script src="assets/demo.js"></script>\n'
html = (static / "index.html").read_text(encoding="utf-8")
html = html.replace('<script src="assets/js/core.js"></script>', inject + '<script src="assets/js/core.js"></script>', 1)
(out / "index.html").write_text(html, encoding="utf-8")
(root / "docs" / ".nojekyll").touch()
print(f"docs/demo updated (v{version})")
PY
