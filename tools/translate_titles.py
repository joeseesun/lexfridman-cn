#!/usr/bin/env python3
"""批量翻译期标题：Magpie 订阅路由（trae→opencode→workbuddy 轮换，官方 deepseek 已退役）。
输出 tools/translations.json（slug → {zh, guest, desc}），增量保存，断点续跑。"""
import json, os, re, subprocess, sys, time, urllib.error, urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent
OUT = ROOT / 'translations.json'
BATCH = 16

API = 'https://magpie.qiaomu.ai/v1/chat/completions'
MODELS = ['trae-cn/deepseek-v4.1-flash', 'opencode-go/deepseek-v4.1-flash', 'workbuddy/deepseek-v4.1-flash']
KEY = os.environ.get('MAGPIE_API_KEY') or subprocess.run(  # 服务器读环境变量，本机读钥匙串
    ['security', 'find-generic-password', '-s', 'qiaomu-llm', '-a', 'magpie', '-w'],
    capture_output=True, text=True).stdout.strip()
assert KEY, 'keychain key not found'

master = json.load(open(ROOT / 'lex-master.json'))
done = json.load(open(OUT)) if OUT.exists() else {}
todo = [e for e in master if e['slug'] not in done]
print(f'total {len(master)}, done {len(done)}, todo {len(todo)}')

PROMPT = """你是资深播客中文编辑。下面是 Lex Fridman 播客若干期的英文标题（JSON 数组，项含 slug/num/title）。
为每一项生成三个字段：
- zh：完整标题的简体中文翻译。人名用通行中文译名（Elon Musk→埃隆·马斯克，较冷门人物保留英文原名亦可）；技术术语用中文圈通行译法，AGI/LLM/CPU 等缩写可保留；期号保留「#N 」前缀（无期号则不加）。
- guest：这期的嘉宾或主题的简短中文名（4-20 字），作为列表卡片上的主标题，如「埃隆·马斯克」「FFmpeg 与视频技术」「外星文明之辩」。
- desc：一句话中文简介（30-55 字），概括这期主要聊什么；不要「本期」「节目中」这类字眼，不要营销腔和感叹号。
只输出 JSON 对象：{"items":[{"slug":"...","zh":"...","guest":"...","desc":"..."}]}，不要输出其他任何文字。"""


def call(items, attempt=1):
    model = MODELS[(attempt - 1) % len(MODELS)]
    payload = {
        'model': model,
        'messages': [{'role': 'user', 'content': PROMPT + '\n\n输入：\n' + json.dumps(items, ensure_ascii=False)}],
        'max_tokens': 6000,
        'temperature': 0.3,
    }
    try:
        return _post({**payload, 'response_format': {'type': 'json_object'}})
    except urllib.error.HTTPError as e:
        if e.code == 400:  # 该路由不认 response_format，去掉重试
            return _post(payload)
        raise


def _post(body_obj):
    body = json.dumps(body_obj).encode()
    req = urllib.request.Request(API, data=body, headers={
        'Authorization': f'Bearer {KEY}', 'Content-Type': 'application/json'})
    with urllib.request.urlopen(req, timeout=180) as r:
        resp = json.load(r)
    content = resp['choices'][0]['message']['content']
    data = json.loads(content)
    got = {}
    for it in data.get('items', []):
        slug = it.get('slug')
        if slug and it.get('zh') and it.get('guest') and it.get('desc'):
            got[slug] = {'zh': it['zh'].strip(), 'guest': it['guest'].strip(), 'desc': it['desc'].strip()}
    return got


flush_at = 0
for bi in range(0, len(todo), BATCH):
    chunk = todo[bi:bi + BATCH]
    items = [{'slug': e['slug'], 'num': e.get('num'), 'title': e['title']} for e in chunk]
    for attempt in range(1, 4):
        try:
            got = call(items)
            if got:
                done.update(got)
                OUT.write_text(json.dumps(done, ensure_ascii=False, indent=0))
                print(f'batch {bi//BATCH+1}: +{len(got)}/{len(chunk)} (total {len(done)})')
                break
            raise ValueError('no items parsed')
        except Exception as e:
            print(f'batch {bi//BATCH+1} attempt {attempt} failed: {type(e).__name__} {e}')
            time.sleep(3 * attempt)
    else:
        miss = [e['slug'] for e in chunk if e['slug'] not in done]
        print('  STILL MISSING:', miss)
    time.sleep(0.5)

miss = [e['slug'] for e in master if e['slug'] not in done]
print(f'FINISHED total={len(done)} missing={len(miss)} {miss[:10]}')
