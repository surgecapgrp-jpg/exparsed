#!/usr/bin/env python3
"""Pull the pure parsing functions out of exparsed.html so JavaScriptCore can run them.

exparsed.html is one page with no build step and its functions live inside the page script,
so the tests cut the relevant sections out by their section markers (no DOM code is included).
Writes <out>/lg.js (the functions) and <out>/all.js (the whole page script, for a syntax check).
"""
import os, re, sys
src, out = sys.argv[1], sys.argv[2]
s = open(src, encoding='utf-8').read()
def cut(a, b):
    i = s.index(a); j = s.index(b, i); return s[i:j]
parts = [cut('    /* ============ EXTRACTION', '    function extract(file)'),
         cut('    var COMMON_WORDS=', '    // Handle UTF-8'),
         cut('    function parseCsvText', '    // Score delimiter'),
         cut('    /* ============ MARKDOWN BUILD', '    // Memoized.'),
         cut('    function splitMdRow', '    function parseMarkdownTables'),
         cut('    var LG_MONTHS=', '    /* ---------- dispatch'),
         cut('    function lgFinalize', '    /* ---------- source ownership'),
         cut('    /* ---------- source ownership', '    /* ============ RENDER')]
os.makedirs(out, exist_ok=True)
open(os.path.join(out, 'lg.js'), 'w', encoding='utf-8').write('\n'.join(parts))
open(os.path.join(out, 'all.js'), 'w', encoding='utf-8').write('\n;\n'.join(re.findall(r'<script>([\s\S]*?)</script>', s)))
