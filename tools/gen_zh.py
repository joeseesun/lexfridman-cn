#!/usr/bin/env python3
"""批量生成《中文精读》：把每期文稿喂给 Magpie deepseek-flash，按乔木风格提示词改写成 HTML 片段。

- 断点续跑：site/zh/{slug}.html 已存在即跳过
- 超长文稿（>350KB，单次调用可能超上下文）走两段笔记 + 成文
- 校验器检查禁用句式/破折号/Markdown 残留/篇幅，不合格带反馈重试
- --watch：循环扫新文稿（配合 ASR 批量进程），连续 3 轮无新增则退出
- 每生成 30 篇自动 build.py + rsync 增量部署
"""
import json
import os
import re
import subprocess
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import requests

ROOT = Path('/Users/joe/Documents/ChatGPT/lex')
SITE = ROOT / 'site'
ZH_DIR = SITE / 'zh'
OT_DIR = ROOT / 'tools' / 'official'
TR_DIR = SITE / 'transcripts'
INDEX_FILE = SITE / 'data' / 'zh-index.json'

BASE_URL = 'https://magpie.qiaomu.ai/v1'
# 动态质量路由（2026-10-18 用户指定）：主力拿多数流量，每 4 篇探测次席；
# 按实测成功率（Laplace 平滑）+ 违规率自动升降位，状态持久化在 tools/zh_model_stats.json。
# 官方 deepseek/* 路由不参与（余额易 402）。思考路由必须 16384 预算，否则 reasoning 吃满、正文为空。
MODELS_ALL = [
    'opencode-go/deepseek-v4.1-flash',
    'trae-cn/deepseek-v4.1-flash',
    'workbuddy/deepseek-v4.1-flash',
    'bigmodel-preview/glm-x-preview-f',
]
MT_OVERRIDES = {
    'opencode-go/deepseek-v4.1-flash': 16384,
    'bigmodel-preview/glm-x-preview-f': 16384,
}
MAX_TOKENS = 8192

STATS_FILE = ROOT / 'zh_model_stats.json'
SEED_STATS = {  # 冷启动种子 = 2026-10-18 真实 34KB 文稿实测
    'opencode-go/deepseek-v4.1-flash': {'ok': 1, 'fail': 0, 'viol': 1},
    'trae-cn/deepseek-v4.1-flash': {'ok': 1, 'fail': 0, 'viol': 2},
    'workbuddy/deepseek-v4.1-flash': {'ok': 1, 'fail': 0, 'viol': 1},
    'bigmodel-preview/glm-x-preview-f': {'ok': 0, 'fail': 2, 'viol': 0},
}
_stats = None
_stats_lock = threading.Lock()
_last_ok_model = [None]   # chat() 成功时记录实际产出模型，用于质量归因


def load_stats():
    global _stats
    if _stats is None:
        try:
            _stats = json.load(open(STATS_FILE))
        except Exception:
            _stats = json.loads(json.dumps(SEED_STATS))
    return _stats


def model_score(m):
    st = load_stats().get(m, {'ok': 0, 'fail': 0, 'viol': 0})
    n = st['ok'] + st['fail']
    return (st['ok'] + 1) / (n + 2) - 0.05 * st['viol'] / max(1, n)


def ranked_models():
    return sorted(MODELS_ALL, key=model_score, reverse=True)


def pick_model(idx, probe_n):
    """idx=尝试序号（0 起）：0 按策略（每 4 篇探测次席），>0 轮换其他模型。"""
    order = ranked_models()
    if idx == 0:
        return order[1] if (probe_n % 4 == 3 and len(order) > 1) else order[0]
    return order[idx % len(order)]


def record_result(model, ok, viol):
    with _stats_lock:
        st = load_stats().setdefault(model, {'ok': 0, 'fail': 0, 'viol': 0})
        st['ok' if ok else 'fail'] += 1
        st['viol'] += viol
        try:
            json.dump(_stats, open(STATS_FILE, 'w'), ensure_ascii=False, indent=1)
        except Exception:
            pass
        top = ranked_models()[0]
        if record_result.announced != top:
            record_result.announced = top
            print(f'primary model: {top}  (scores: '
                  + ', '.join(f'{m.split("/")[-1]}={model_score(m):.2f}' for m in ranked_models()) + ')', flush=True)


record_result.announced = None
CHUNK_BYTES = 350_000          # 超过则两段笔记 + 成文
WORKERS = 4
DEPLOY_EVERY = 30
WATCH_INTERVAL = 600

_api_key = None

def api_key():
    global _api_key
    if _api_key is None:
        _api_key = subprocess.run(
            ['security', 'find-generic-password', '-s', 'qiaomu-llm', '-a', 'magpie', '-w'],
            capture_output=True, text=True, check=True).stdout.strip()
    return _api_key

SYSTEM = """你是向阳乔木，一位中文科技内容作者。擅长把信息密度高的英文报告、机器翻译稿或直播文字稿，改写成逻辑清晰、读感流畅的中文文章。
目标读者是有一定技术背景的从业者，时间有限，不喜欢废话，但愿意为真正有价值的内容停下来细读。

---

## 语言风格

- 口语化，对话感强，像和读者面对面聊天
- 短段落，多留白，视觉舒适
- 善用生活化类比解释复杂概念，在专业性和可读性之间自然平衡
- 始终使用第三人称视角叙述
- 真诚、不装，承认困惑，专业但不掉书袋
- 数据和案例支撑观点，有洞察力，给读者"原来如此"的感觉
- **直接陈述事实和观点，不给内容贴标签**。不说"这是一个反直觉的数据"，直接说数据是什么。不说"这不是概念演示"，直接说这是什么。让内容本身说话，不要提前定性

---

## 格式规范

- 重要观点用**加粗**突出
- 全程使用中文标点：逗号（，）句号（。）冒号（：）问号（？）顿号（、）书名号（《》）
- 禁止使用中文破折号和英文破折号
- 禁止使用 `---` 水平分隔线，h2/h3 标题本身已做内容分割，再加横线是多余的视觉噪音
- 原文中的图片 Markdown 引用原样保留，位置与上下文匹配

---

## 禁用表达

以下词汇和句式有明显的 AI 生成感，一律不用：

**句式禁用：**
不是……而是、想象一下、你有没有想过、值得注意的是、不难理解、毋庸置疑、随着……的发展、对于……来说、在……方面

**词汇禁用：**
精准打击、赋能、落地、深度融合、全面布局、强势崛起等空洞的、无信息量的套话

**贴标签式开场禁用（重点）：**
禁止用"这是一个反直觉的数字"、"这不是什么概念演示"、"一个尖锐的问题是"这类先给内容定性、再解释内容的句式。这种写法看似是钩子，实际是把判断强加给读者，是典型的 AI 腔。

正确做法：直接把数据或事实摆出来，让反差和信息量自己显现。比如不说"一个反直觉的数字：65%的PR是AI合并的"，而是直接写"Anthropic 内部产品工程团队，现在有65%的PR是由一个叫Claude Tag的机器人直接合并进主干的"，用后一句的信息密度本身制造冲击力。

**预告式渲染表达禁用：**
"最让我吃惊的是"、"最扎心的是"、"最意外的是"这类预告句式，如果后面的内容配不上这种渲染强度，就是空话。用具体细节代替情绪预告。

**过度解释禁用：**
每个数据后面跟"这说明什么"是对的，但不要每一段都用同一个句式（"这说明""这意味着""这背后是"）来引出解读，会显得机械。可以直接把因果关系写进叙述里，不必每次单独起一句总结。

---

## 写作结构

**开头**
必须有钩子：一个反常识的数据、一个尖锐的问题，或一个让人想继续读下去的矛盾。
钩子本身要靠信息量制造冲击，不要靠"这是一个……"这类前置定性语句来提示读者应该感到意外。直接陈述事实，让读者自己得出"这很反直觉"的结论。

**正文**
- 每个段落只说一件事
- 每一个数据后面，跟上"这说明什么"，但避免用重复的固定句式引出
- 因果关系写清楚，不只是并列事实，尽量把因果关系自然嵌入叙述，少用单独的总结句
- 遇到反直觉的结论，在读者产生疑问之前主动解释，但不要提前说"这很反直觉"
- 不满足于表面解释，延伸到更深的思考
- 善于在不同领域间建立联系（技术、生活、认知）
- 小标题要有实际信息量，不用"背景介绍""数据分析"这类无意义的标题

**结尾**
给出一个对读者真正有用的行动结论，不做空泛总结。

---

## 忠实度要求

- 保留原文所有关键数据和核心结论，不遗漏，不夸大
- 可以调整结构和顺序，但不能改变原意
- 如果原始材料是直播或访谈文字稿，AI 语音识别可能存在错误，尽可能理解实际想表达的内容和专业名词，合理还原

---

## 本次任务的特殊约定（输出格式）

1. 输入材料是 Lex Fridman 播客某一期的英文完整文字稿，可能来自语音识别（ASR），含同音词错误和人名拼写错误，按上下文合理还原专业名词。
2. 输出一个完整的 HTML 片段，只允许这些标签：p、h2、ul、ol、li、blockquote、strong、em。
3. 严禁出现任何 Markdown 语法：不加粗星号、不用井号标题、不用 > 引用符、不用代码围栏。加粗一律写 <strong>，小标题一律写 <h2>，引用嘉宾原话一律写 <blockquote>（翻译成中文，句末用括号注明说话人，可保留个别英文关键词）。
4. 不要 h1，不要 <html>、<body> 等外层标签，不要任何解释或前言，直接从第一个 <p> 开始输出。
5. 全文简体中文，专有名词首次出现时可括注英文原名。正文不少于 5000 个汉字；文字稿特别长的访谈（超过 4 小时）写足 6000 到 7500 字。
6. 结尾的行动结论用一个 ul 列表呈现，给读者可操作的具体建议。
"""

FORBIDDEN = [
    (r'不是[^。\n]{0,15}而是', '句式"不是……而是"'),
    (r'想象一下', '句式"想象一下"'),
    (r'你有没有想过', '句式"你有没有想过"'),
    (r'值得注意的是', '句式"值得注意的是"'),
    (r'不难理解', '句式"不难理解"'),
    (r'毋庸置疑', '词汇"毋庸置疑"'),
    (r'让我们', '句式"让我们"'),
    (r'关键在于', '句式"关键在于"'),
    (r'这是一个', '贴标签开场"这是一个"'),
    (r'最让我吃惊|最扎心|最意外的是', '预告式渲染'),
    (r'总之|综上所述|总而言之', '空泛总结词'),
    (r'精准打击|赋能|深度融合|全面布局|强势崛起', '空洞套话'),
    (r'随着[^。\n]{0,20}的发展', '句式"随着……的发展"'),
    (r'对于[^。\n]{0,10}来说', '句式"对于……来说"'),
    (r'在[^。，\n]{1,6}方面', '句式"在……方面"'),
]
DASH_RE = re.compile(r'——|—|–|--')
ALLOWED_TAGS = {'p', 'h2', 'h3', 'ul', 'ol', 'li', 'blockquote', 'strong', 'em', 'br'}


def transcript_source(slug):
    for d in (OT_DIR, TR_DIR):
        f = d / f'{slug}.txt'
        if f.exists() and f.stat().st_size > 0:
            return f
    return None


def min_chars(size):
    if size >= 300_000:
        return 5000
    if size >= 100_000:
        return 4200
    if size >= 30_000:
        return 3200
    return 1800


def chat(messages, max_tokens=MAX_TOKENS, timeout=1200, model=None):
    """动态路由调用：从 model（缺省榜首）起，遇 4xx 或纯思考响应按实时质量排序换下一家。"""
    global _last_ok_model
    order = ranked_models()
    start = order.index(model) if model in order else 0
    last = None
    for hop in range(len(order)):
        cur = order[(start + hop) % len(order)]
        for attempt in range(6):
            try:
                r = requests.post(
                    f'{BASE_URL}/chat/completions',
                    headers={'Authorization': f'Bearer {api_key()}',
                             'Content-Type': 'application/json'},
                    json={'model': cur, 'messages': messages, 'max_tokens': MT_OVERRIDES.get(cur, max_tokens),
                          'temperature': 0.7},
                    timeout=timeout)
                if r.status_code in (400, 401, 402, 403):
                    last = f'HTTP {r.status_code} on {cur}: {r.text[:150]}'
                    print(f'model down: {cur} ({r.status_code}), next in ladder', flush=True)
                    break
                if r.status_code == 429 or r.status_code >= 500:
                    last = f'HTTP {r.status_code}: {r.text[:200]}'
                    time.sleep(min(300, 8 * 2 ** attempt))
                    continue
                r.raise_for_status()
                data = r.json()
                msg = data['choices'][0]['message']
                content = msg.get('content') or ''
                if not content.strip() and msg.get('reasoning_content'):
                    # 思考模型把输出预算全花在 reasoning 上，拿不到正文，换下一家
                    last = f'{cur}: reasoning-only response, no content'
                    print(f'model unusable: {cur} (reasoning ate the budget), next in ladder', flush=True)
                    break
                _last_ok_model[0] = cur
                return content, data['choices'][0].get('finish_reason', '')
            except requests.RequestException as e:
                last = f'{cur}: {str(e)[:250]}'
                time.sleep(min(300, 8 * 2 ** attempt))
    raise RuntimeError(f'chat failed across ladder: {last}')


def chat_full(messages, model=None):
    """带续写：finish_reason=length 时接续，避免 8192 token 截断。"""
    out, msgs = '', list(messages)
    for _ in range(5):
        text, reason = chat(msgs, model=model)
        out += text
        if reason != 'length' or not text.strip():
            return out
        msgs = msgs + [{'role': 'assistant', 'content': text},
                       {'role': 'user', 'content': '继续输出剩余部分，从中断处接着写，不要重复已有内容，也不要重新开头。'}]
    return out


def clean(text):
    text = text.strip()
    text = re.sub(r'^```(?:html)?\s*\n?', '', text)
    text = re.sub(r'\n?```\s*$', '', text)
    m = re.search(r'<(?:p|h2|ul|ol|blockquote)[ >]', text)
    if m and m.start() > 0:
        text = text[m.start():]
    return text.strip()


def validate(html, size):
    problems = []
    for tag in set(re.findall(r'</?([a-zA-Z0-9]+)[ >/]', html)):
        if tag.lower() not in ALLOWED_TAGS:
            problems.append(f'出现不允许的标签 <{tag}>')
    for pat, label in FORBIDDEN:
        hits = re.findall(pat, html)
        if hits:
            problems.append(f'{label}（{hits[0][:30]}）')
    if DASH_RE.search(html):
        problems.append('出现破折号')
    if re.search(r'\*\*|^#{1,6}\s|^\s*>|```|^\s*[-*]\s', html, re.M):
        problems.append('残留 Markdown 语法')
    if '<h2' not in html:
        problems.append('缺少 h2 小标题')
    plain = re.sub(r'<[^>]+>', '', html)
    cjk = len(re.findall(r'[\u4e00-\u9fff]', plain))
    if cjk < min_chars(size):
        problems.append(f'篇幅不足：正文汉字 {cjk}，要求 ≥ {min_chars(size)}')
    return problems, cjk


def take_notes(chunk, part, model=None):
    msgs = [{'role': 'system', 'content':
             '你是研究助理。从播客访谈文字稿片段中提取详尽的中文笔记，逐条列出：关键论点、数据、故事、分歧与结论。'
             '保留其中最有力的 8-12 句原话（英文原句照抄，注明说话人）。不要评论，只要事实要点。'}]
    msgs.append({'role': 'user', 'content':
                 f'以下是某期访谈文字稿的{part}：\n\n{chunk}\n\n请输出笔记。'})
    return chat(msgs, max_tokens=3000, timeout=900, model=model)[0]


def gen_one(slug, ep, trans, model=None):
    zh = ep['zh'] or ''
    zh = re.sub(r'^(#\d+)\s*[–—-]\s*', r'\1 ', zh)
    meta = (f'节目信息：\n- 第 {ep["num"]} 期\n- 英文标题：{ep["title"]}\n'
            f'- 中文标题：{zh}\n- 嘉宾：{ep.get("guest") or "见标题"}\n'
            f'- 发布日期：{ep["date"]}\n\n')
    if len(trans) > CHUNK_BYTES:
        half = len(trans) // 2
        for cut in (half, half - 20000, half + 20000):
            if trans[cut:cut + 1] in (' ', '\n'):
                half = cut
                break
        notes_a = take_notes(trans[:half], '前半部分', model=model)
        notes_b = take_notes(trans[half:], '后半部分', model=model)
        user = (meta + '以下是对这期访谈两段文字稿的详细笔记（含原话引文），'
                '请基于笔记写一篇覆盖整期内容的《中文精读》，结构、风格、篇幅按系统提示词要求：\n\n'
                '【前半部分笔记】\n' + notes_a + '\n\n【后半部分笔记】\n' + notes_b)
    else:
        user = (meta + '以下是这期访谈的完整英文文字稿：\n\n' + trans +
                '\n\n请写一篇《中文精读》文章，按系统提示词的风格、结构与篇幅要求输出 HTML 片段。')
    msgs = [{'role': 'system', 'content': SYSTEM}, {'role': 'user', 'content': user}]
    html = clean(chat_full(msgs, model=model))
    problems, cjk = validate(html, len(trans))
    for round_no in range(2):
        if not problems:
            return html, cjk, []
        fb = '；'.join(problems)
        msgs = msgs + [{'role': 'assistant', 'content': html},
                       {'role': 'user', 'content':
                        f'你的文章存在问题：{fb}。请重写并输出修订后的完整 HTML 片段（从头到尾完整输出，不要只给修改处），继续满足系统提示词的全部要求。'}]
        html = clean(chat_full(msgs, model=model))
        problems, cjk = validate(html, len(trans))
    return (html, cjk, problems) if not problems else (None, cjk, problems)


def deploy():
    subprocess.run([sys.executable, 'tools/build.py'], cwd=ROOT, check=True,
                   capture_output=True, text=True)
    # 多语言镜像树（/tw 繁体 + /en 英文界面）：build 之后、rsync 之前生成
    subprocess.run([sys.executable, 'tools/gen_i18n.py'], cwd=ROOT, check=True,
                   capture_output=True, text=True)
    subprocess.run(['rsync', '-az', '--delete', '--exclude', '.well-known',
                    'site/', 'qiaomu-hostinger:/www/wwwroot/lex.qiaomu.ai/'],
                   cwd=ROOT, check=True, capture_output=True, text=True)


def main():
    watch = '--watch' in sys.argv
    only = None
    for a in sys.argv[1:]:
        if a.startswith('--only='):
            only = a.split('=', 1)[1]

    master = json.load(open(ROOT / 'tools' / 'lex-master.json'))
    trans_info = json.load(open(ROOT / 'tools' / 'translations.json'))
    eps = {}
    for e in master:
        info = trans_info.get(e['slug'], {})
        eps[e['slug']] = {'num': e.get('num'), 'title': e['title'], 'date': e.get('date', ''),
                          'zh': info.get('zh'), 'guest': info.get('guest')}

    index_lock = threading.Lock()

    def update_index(slug):
        with index_lock:
            data = json.load(open(INDEX_FILE))
            if slug not in data['slugs']:
                data['slugs'].append(slug)
                json.dump(data, open(INDEX_FILE, 'w'), ensure_ascii=False)

    todo = []
    for slug in sorted(eps):
        if only and slug != only:
            continue
        if (ZH_DIR / f'{slug}.html').exists():
            continue
        src = transcript_source(slug)
        if src:
            todo.append((slug, src))
    print(f'todo: {len(todo)} episodes with transcript but no zh', flush=True)
    print(f'model ranking: {ranked_models()}', flush=True)

    attempt_lock = threading.Lock()

    probe_n = 0

    def work(item):
        nonlocal probe_n
        slug, src = item
        with attempt_lock:
            idx = attempts.get(slug, 0)
            attempts[slug] = idx + 1
            if idx == 0:
                probe_n += 1
            model = pick_model(min(idx, len(MODELS_ALL) - 1), probe_n)
        trans = src.read_text(errors='replace')
        t0 = time.time()
        try:
            html, cjk, problems = gen_one(slug, eps[slug], trans, model=model)
        except Exception:
            record_result(model, False, 0)
            raise
        actual = _last_ok_model[0] or model
        if html is None:
            record_result(actual, False, len(problems))
            return slug, None, cjk, time.time() - t0, problems, actual
        record_result(actual, True, 0)
        ZH_DIR.mkdir(exist_ok=True)
        (ZH_DIR / f'{slug}.html').write_text(html)
        update_index(slug)
        return slug, cjk, cjk, time.time() - t0, [], actual

    done = fail = 0
    since_deploy = 0
    failures = {}
    attempts = {}
    rounds_empty = 0
    MAX_ATTEMPTS = 5
    while True:
        with ThreadPoolExecutor(max_workers=WORKERS) as pool:
            futs = {pool.submit(work, it): it[0] for it in todo}
            for fut in as_completed(futs):
                slug = futs[fut]
                try:
                    slug, cjk, _, dt, problems, model = fut.result()
                    if cjk is None or cjk == 0:
                        fail += 1
                        failures[slug] = '; '.join(problems)
                        print(f'FAIL {slug} [{model}] ({dt:.0f}s): {"; ".join(problems)[:300]}', flush=True)
                    else:
                        done += 1
                        since_deploy += 1
                        print(f'OK {slug} chars={cjk} [{model}] ({dt:.0f}s) [{done + fail}]', flush=True)
                except Exception as e:
                    fail += 1
                    failures[slug] = str(e)[:200]
                    print(f'ERR {slug}: {str(e)[:120]}', flush=True)
        if since_deploy >= DEPLOY_EVERY:
            print(f'--- deploying ({since_deploy} new) ---', flush=True)
            try:
                deploy()
                print('deploy ok', flush=True)
            except Exception as e:
                print(f'deploy FAILED: {str(e)[:300]}', flush=True)
            since_deploy = 0
        if not watch:
            break
        time.sleep(WATCH_INTERVAL)
        todo = []
        for slug in sorted(eps):
            if (ZH_DIR / f'{slug}.html').exists():
                continue
            if attempts.get(slug, 0) >= MAX_ATTEMPTS:
                continue
            src = transcript_source(slug)
            if src:
                todo.append((slug, src))
        if todo:
            rounds_empty = 0
            print(f'watch: {len(todo)} to do (incl. retries)', flush=True)
            continue
        asr_alive = subprocess.run(['pgrep', '-f', 'run_asr_batch.py'],
                                   capture_output=True).returncode == 0
        rounds_empty += 1
        print(f'watch: nothing new (round {rounds_empty}, asr_alive={asr_alive})', flush=True)
        if rounds_empty >= 3:
            break
    if since_deploy and done:
        try:
            deploy()
            print('final deploy ok', flush=True)
        except Exception as e:
            print(f'final deploy FAILED: {str(e)[:300]}', flush=True)
    print(f'FINISHED done={done} fail={fail}', flush=True)
    if failures:
        json.dump(failures, open('/tmp/lexsite/gen_zh_failures.json', 'w'),
                  ensure_ascii=False, indent=1)
        print('failures: ' + ', '.join(list(failures)[:20]), flush=True)


if __name__ == '__main__':
    main()
