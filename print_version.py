#!/usr/bin/env python3
"""Print VIGIL_VERSION from app.py — used by build scripts (bat can't regex)."""
import re

src = open("app.py", encoding="utf-8").read()
m = re.search(r'^VIGIL_VERSION\s*=\s*"([^"]+)"', src, re.M)
print(m.group(1) if m else "0.0.0")
