#!/usr/bin/env python3
"""抓取 lexfridman.com 官方文稿页，解析 ts-name/ts-timestamp/ts-text 为纯文本。
输出 tools/official/{slug}.txt；断点续跑（已存在的跳过，--force 重抓）。"""
import json, re, sys, time, html, urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent
OUT = ROOT / 'official'
OUT.mkdir(exist_ok=True)

master = json.load(open(ROOT / 'lex-master.json'))
ot_eps = [e for e in master if e.get('officialTranscript')]
print(f"official transcript episodes: {len(ot_eps)}")

UA = ('Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 '
      '(KHTML, like Gecko) Chrome/126.0 Safari/537.36')
SPAN_RE = re.compile(
    r'<span class="ts-name">(.*?)</span>\s*<span class="ts-timestamp">(.*?)</span>\s*'
    r'<span class="ts-text">(.*?)</span>', re.S)
TS_RE = re.compile(r'\((\d\d:\d\d:\d\d)\)')


def clean(s: str) -> str:
    s = re.sub(r'<[^>]+>', '', s)
    s = html.unescape(s)
    return ' '.join(s.split())


def fetch(slug: str) -> str | None:
    url = f'https://lexfridman.com/{slug}-transcript/'
    req = urllib.request.Request(url, headers={'User-Agent': UA})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            page = r.read().decode('utf-8', 'replace')
    except Exception as e:
        print(f'  FAIL {slug}: {e}')
        return None
    segs = SPAN_RE.findall(page)
    if not segs:
        print(f'  EMPTY {slug} (no ts- segments, page {len(page)}B)')
        return None
    lines = []
    last = ''
    for name, ts, text in segs:
        name = clean(name)
        m = TS_RE.search(ts)
        stamp = m.group(1) if m else ''
        body = clean(text)
        if not body:
            continue
        if not name and last:
            name = last
        if name:
            last = name
        lines.append(f'{name} ({stamp}): {body}' if stamp else f'{name}: {body}')
    return '\n'.join(lines)


force = '--force' in sys.argv
ok = fail = skip = 0
for i, e in enumerate(ot_eps):
    slug = e['slug']
    dest = OUT / f'{slug}.txt'
    if dest.exists() and not force:
        skip += 1
        continue
    text = fetch(slug)
    if text:
        dest.write_text(text)
        ok += 1
    else:
        fail += 1
    if (i + 1) % 20 == 0:
        print(f'  ... {i+1}/{len(ot_eps)}')
    time.sleep(0.4)

print(f'done: ok={ok} fail={fail} skip={skip} total_files={len(list(OUT.glob("*.txt")))}')
