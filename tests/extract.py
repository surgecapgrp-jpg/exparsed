#!/usr/bin/env python3
"""Pull the parsing script out of exparsed.html so JavaScriptCore or node can run it.

The page keeps everything that turns file bytes into ledgers in <script id="exparsed-core">,
with no DOM state, so the tests load that script whole.
Writes <out>/lg.js (the parsing script) and <out>/all.js (every inline script, for a syntax check).
"""
import os, re, sys
src, out = sys.argv[1], sys.argv[2]
s = open(src, encoding='utf-8').read()
core = re.search(r'<script id="exparsed-core">([\s\S]*?)</script>', s)
if not core:
    sys.exit('extract.py: <script id="exparsed-core"> not found in ' + src)
os.makedirs(out, exist_ok=True)
open(os.path.join(out, 'lg.js'), 'w', encoding='utf-8').write(core.group(1))
open(os.path.join(out, 'all.js'), 'w', encoding='utf-8').write('\n;\n'.join(re.findall(r'<script(?: id="[^"]*")?>([\s\S]*?)</script>', s)))
