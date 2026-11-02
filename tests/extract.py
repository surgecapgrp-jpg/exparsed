#!/usr/bin/env python3
"""Pull the pure parsing functions out of exparsed.html so JavaScriptCore can run them.

exparsed.html is one page with no build step and its functions live inside the page script,
so the tests take every region marked /* @test-begin NAME */ ... /* @test-end */ (no DOM code
goes inside one). Writes <out>/lg.js (the regions, in page order) and <out>/all.js (the whole
page script, for a syntax check).
"""
import os, re, sys
src, out = sys.argv[1], sys.argv[2]
s = open(src, encoding='utf-8').read()
begins, ends = s.count('/* @test-begin '), s.count('/* @test-end */')
regions = re.findall(r'/\* @test-begin [\w-]+ \*/\n([\s\S]*?)\n    /\* @test-end \*/', s)
if not regions or begins != ends or len(regions) != begins:
    sys.exit(f'extract: {begins} @test-begin, {ends} @test-end, {len(regions)} regions read; markers must pair up')
os.makedirs(out, exist_ok=True)
open(os.path.join(out, 'lg.js'), 'w', encoding='utf-8').write('\n'.join(regions))
open(os.path.join(out, 'all.js'), 'w', encoding='utf-8').write('\n;\n'.join(re.findall(r'<script>([\s\S]*?)</script>', s)))
