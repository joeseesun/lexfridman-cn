#!/usr/bin/env python3
"""同步新一期：官方 RSS → lex-master.json / feed_audio.json → 标题翻译 → 文稿 → 精读管线。

流程（gen_zh --watch 负责其后的精读生成与增量部署，本脚本保证它有料可扫）：
1. 抓 lexfridman.com/feed/，识别「#N –」期目与「Transcript for …」官方文稿条目
2. 与 lex-master.json 对账：新期补 master（ytId 从单集页抓，按期号插位保持顺序）；
   官方文稿已上线但 master 未记的 → 回填 officialTranscript
3. feed_audio.json 补 by_num / by_slug
4. 跑 fetch_official.py（断点续跑，只抓缺的官方文稿）
5. 新期跑 translate_titles.py（增量，只补缺的 slug）
6. 仍无文稿的新期：下载官方 MP3 → 本地 mlx_whisper 转写 → site/transcripts/{slug}.txt
7. gen_zh --watch 未在跑则拉起；有变更时立即 build + rsync 一次

用法：python3 tools/sync_new.py [--dry-run] [--no-asr]
"""
import fcntl
import json
import os
import re
import html as HH
import subprocess
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent            # tools/
REPO = ROOT.parent
SITE = REPO / 'site'
TMP = Path('/tmp/lexsite/sync')
UA = ('Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 '
      '(KHTML, like Gecko) Chrome/126.0 Safari/537.36')
EP_RE = re.compile(r'^#(\d+)\s*[–—-]\s*(.*)$', re.S)
YT_RE = re.compile(r'youtube\.com/(?:embed/|watch\?v=)([A-Za-z0-9_-]{6,14})|youtu\.be/([A-Za-z0-9_-]{6,14})')
DRY = '--dry-run' in sys.argv
PUSH = '--no-push' not in sys.argv
WHISPER = os.environ.get('MLX_WHISPER', '/opt/homebrew/bin/mlx_whisper')  # launchd 下 PATH 很精简，用绝对路径
ASR_ENGINE = os.environ.get('ASR_ENGINE', 'mlx')       # 服务器上为 doubao（豆包录音文件识别）
DEPLOY_TARGET = os.environ.get('LEX_DEPLOY_TARGET', 'qiaomu-hostinger:/www/wwwroot/lex.qiaomu.ai/')
QMREADER = os.environ.get('QMREADER_URL', '')          # 设置后，部署完通知 QMReader 刷新对应源
QMREADER_SOURCE = 'lex-zh'
OPS = Path(os.environ.get('PODCAST_OPS', '/Users/joe/Documents/ChatGPT/podcast-ops'))
DO_ASR = '--no-asr' not in sys.argv

changes = []


def log(msg):
    print(msg, flush=True)


def get(url, timeout=30, retries=3):
    req = urllib.request.Request(url, headers={'User-Agent': UA})
    for i in range(retries):
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return r.read()
        except urllib.error.HTTPError:
            raise
        except Exception as e:
            if i == retries - 1:
                raise
            log(f'  网络重试 {i + 1}/{retries - 1}: {url[:70]} ({type(e).__name__})')
            time.sleep(2 * (i + 1))


def write_json(path, data):
    if DRY:
        return
    out = json.dumps(data, ensure_ascii=False, indent=1)
    if not out.endswith('\n'):
        out += '\n'
    path.write_text(out)


def load_master():
    m = json.load(open(ROOT / 'lex-master.json'))
    return m


def save_master(m):
    write_json(ROOT / 'lex-master.json', m)


def parse_rss():
    xml = get('https://lexfridman.com/feed/').decode('utf-8', 'ignore')
    eps, ots = [], {}
    for it in re.findall(r'<item>(.*?)</item>', xml, re.S):
        title = HH.unescape((re.search(r'<title>(.*?)</title>', it, re.S).group(1)).strip())
        link = re.search(r'<link>(.*?)</link>', it).group(1).strip()
        pd = re.search(r'<pubDate>(.*?)</pubDate>', it)
        enc = re.search(r'<enclosure[^>]*url="([^"]+)"', it)
        slug_m = re.match(r'https://lexfridman\.com/([^/?#]+)/?', link)
        if not slug_m:
            continue
        slug = slug_m.group(1)
        if slug.endswith('-transcript'):
            ots[slug[:-len('-transcript')]] = True
            continue
        num_m = EP_RE.match(title)
        if not num_m:   # 纯 solo/公告贴，跳过（罕见，手工处理）
            log(f'  跳过非期目条目: {title[:50]}')
            continue
        date = ''
        if pd:
            try:
                date = parsedate_to_datetime(pd.group(1)).astimezone(timezone.utc).date().isoformat()
            except Exception:
                pass
        eps.append({'num': int(num_m.group(1)), 'title': title, 'slug': slug,
                    'date': date, 'enc': enc.group(1) if enc else None})
    return eps, ots


def fetch_yt_id(slug):
    try:
        page = get(f'https://lexfridman.com/{slug}/', timeout=20).decode('utf-8', 'ignore')
        m = YT_RE.search(page)
        return m.group(1) or m.group(2) if m else None
    except Exception as e:
        log(f'  ytId 获取失败 {slug}: {type(e).__name__}')
        return None


def insert_sorted(master, entry):
    """按期号降序插位（master 现序即构建用的 prev/next 顺序），不动其他条目。"""
    idx = len(master)
    for i, e in enumerate(master):
        if e.get('num') is not None and e['num'] < entry['num']:
            idx = i
            break
    master.insert(idx, entry)


def asr_transcript(e, audio):
    """官方音频 → 转写 → site/transcripts/{slug}.txt（与既有 ASR 文稿同格式）。
    ASR_ENGINE=doubao 时把音频 URL 交给豆包（服务器上用）；否则下载后本地 mlx_whisper。"""
    TMP.mkdir(parents=True, exist_ok=True)
    label = f"#{e['num']} – {e['title'].split('–', 1)[-1].strip()}" if e['num'] else e['title']
    out = SITE / 'transcripts' / f"{e['slug']}.txt"
    if ASR_ENGINE == 'doubao':
        sys.path.insert(0, str(OPS))
        from doubao_asr import transcribe
        log('  豆包录音文件识别中 …')
        text = transcribe(audio, lang='en-US')
        out.write_text(f'Lex Fridman Podcast {label}\n'
                       'Machine transcription by Doubao ASR (Volcengine, cloud). May contain recognition errors.\n\n'
                       + text + '\n')
        log(f"  已转写 {out.name}（{len(text)} 字符）")
        return
    mp3 = TMP / f"{e['slug']}.mp3"
    log(f"  下载音频 {audio.rsplit('/', 1)[-1]} …")
    mp3.write_bytes(get(audio, timeout=600))
    outdir = TMP / 'asr'
    subprocess.run([WHISPER, str(mp3), '--model', 'mlx-community/whisper-large-v3-turbo',
                    '--language', 'en', '--output-dir', str(outdir), '--output-format', 'txt'],
                   check=True, capture_output=True)
    raw = (outdir / f"{e['slug']}.txt").read_text()
    lines = []
    for ln in raw.splitlines():
        m = re.match(r'^\[\d+:\d+(?::\d+)?\.\d+ --> [\d:.]+\]\s*(.*)$', ln)
        seg = m.group(1).strip() if m else ln.strip()
        if seg:
            lines.append(seg)
    text = re.sub(r'\s+([,.!?;:])', r'\1', ' '.join(lines))
    hdr = (f'Lex Fridman Podcast {label}\n'
           'Machine transcription by Whisper large-v3-turbo (MLX, local). May contain recognition errors.\n\n')
    out.write_text(hdr + text + '\n')
    mp3.unlink(missing_ok=True)
    log(f"  已转写 {out.name}（{len(text)} 字符）")


def ensure_watch():
    r = subprocess.run(['pgrep', '-f', 'gen_zh.py --watch'], capture_output=True, text=True)
    if r.stdout.strip():
        return
    if DRY:
        log('  [dry-run] 需要拉起 gen_zh --watch')
        return
    logf = open('/tmp/lexsite/gen_zh.log', 'a')
    subprocess.Popen([sys.executable, str(ROOT / 'gen_zh.py'), '--watch'],
                     cwd=REPO, stdout=logf, stderr=logf, start_new_session=True)
    log('  gen_zh --watch 已拉起（日志 /tmp/lexsite/gen_zh.log）')


def deploy():
    subprocess.run([sys.executable, 'tools/build.py'], cwd=REPO, check=True, capture_output=True)
    subprocess.run(['rsync', '-az', '--delete', '--exclude', '.well-known',
                    'site/', DEPLOY_TARGET],
                   cwd=REPO, check=True, capture_output=True)
    log('  build + rsync 完成')
    notify_qmreader()


def notify_qmreader():
    if not QMREADER:
        return
    try:
        req = urllib.request.Request(f'{QMREADER}/api/sources/{QMREADER_SOURCE}/refresh-hint', data=b'{}', method='POST',
                                     headers={'Content-Type': 'application/json'})
        log('  已通知 QMReader 刷新：' + urllib.request.urlopen(req, timeout=20).read().decode()[:120])
    except Exception as ex:
        log(f'  通知 QMReader 失败：{ex}')


def git_commit_push(reason):
    """把已落盘的精读与元数据提交并推送 main（精读由后台 gen_zh 异步生成，所以每次运行开头先收上一轮的成果）。
    推送失败只记日志，不算整体失败。"""
    if DRY or not PUSH:
        return
    git = lambda *a: subprocess.run(['git', *a], cwd=REPO, capture_output=True, text=True)  # noqa: E731
    git('add', 'site/zh', 'site/data/zh-index.json', 'tools/lex-master.json', 'tools/feed_audio.json',
        'tools/translations.json', 'tools/og-faces.json')
    if git('diff', '--cached', '--quiet').returncode == 0:
        return
    n = len([x for x in git('diff', '--cached', '--name-only').stdout.split() if x.startswith('site/zh/')])
    git('commit', '-m', f'每日追新 {datetime.now():%Y-%m-%d}：{reason}' + (f'（新增 / 更新精读 {n} 篇）' if n else ''))
    r = git('push', '-q', 'origin', 'HEAD')
    log('GitHub 推送' + ('完成' if r.returncode == 0 else f'失败：{r.stderr.strip()[-200:]}'))


def main():
    lock = open('/tmp/lexsite-sync.lock', 'w')
    try:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        log('上一次追新仍在运行，本次跳过')
        return
    TMP.mkdir(parents=True, exist_ok=True)
    log(f'== sync_new start {datetime.now().isoformat(timespec="seconds")} ==')
    git_commit_push('收录上一轮精读')
    eps, ots = parse_rss()
    log(f'RSS: {len(eps)} 期目, {len(ots)} 个官方文稿条目')
    master = load_master()
    known_slugs = {e['slug'] for e in master}
    known_nums = {e.get('num') for e in master}
    feed_audio = json.load(open(ROOT / 'feed_audio.json'))

    # 1) 官方文稿回填（已收录期）
    ot_filled = []
    for e in master:
        if e['slug'] in ots and not e.get('officialTranscript'):
            e['officialTranscript'] = f"https://lexfridman.com/{e['slug']}-transcript/"
            ot_filled.append(e['slug'])
    if ot_filled:
        log(f'回填 officialTranscript: {ot_filled}')
        save_master(master)
        changes.append('officialTranscript 回填')

    # 2) 新期入 master
    new_eps = [e for e in eps if e['slug'] not in known_slugs and e['num'] not in known_nums]
    if new_eps:
        for e in sorted(new_eps, key=lambda x: x['num']):
            log(f"新期 #{e['num']} {e['slug']} ({e['date']})")
            entry = {'num': e['num'], 'title': e['title'], 'date': e['date'], 'slug': e['slug'],
                     'lexUrl': f"https://lexfridman.com/{e['slug']}/",
                     'ytId': fetch_yt_id(e['slug']),
                     'officialTranscript': (f"https://lexfridman.com/{e['slug']}-transcript/"
                                            if e['slug'] in ots else None),
                     'hsUrl': None, 'kaggleText': None}
            insert_sorted(master, entry)
            if e['enc']:
                feed_audio['by_num'][str(e['num'])] = e['enc']
                feed_audio['by_slug'][e['slug']] = e['enc']
        save_master(master)
        write_json(ROOT / 'feed_audio.json', feed_audio)
        log(f'master 已加 {len(new_eps)} 期；feed_audio 已补音频直链')
        changes.append(f'{len(new_eps)} 个新期')

    # 3) 官方文稿下载（回填 + 新期；脚本自身断点续跑）
    if ot_filled or new_eps:
        log('跑 fetch_official.py …')
        if not DRY:
            subprocess.run([sys.executable, str(ROOT / 'fetch_official.py')], cwd=REPO)

    # 4) 标题翻译（增量，只补缺）
    trans = json.load(open(ROOT / 'translations.json')) if (ROOT / 'translations.json').exists() else {}
    need_tr = [e['slug'] for e in master if e['slug'] not in trans]
    if need_tr:
        log(f'标题翻译缺 {len(need_tr)}: {need_tr[:5]}')
        if not DRY:
            subprocess.run([sys.executable, str(ROOT / 'translate_titles.py')], cwd=REPO)

    # 5) 无文稿的新期 → ASR
    if DO_ASR and new_eps:
        fa = json.load(open(ROOT / 'feed_audio.json'))
        for e in new_eps:
            has = (ROOT / 'official' / f"{e['slug']}.txt").exists() or (SITE / 'transcripts' / f"{e['slug']}.txt").exists()
            if has:
                continue
            audio = fa['by_num'].get(str(e['num'])) or fa['by_slug'].get(e['slug'])
            if not audio:
                log(f"  {e['slug']} 无音频直链，跳过 ASR（需手工）")
                continue
            log(f"  ASR {e['slug']} …")
            if not DRY:
                asr_transcript({'num': e['num'], 'slug': e['slug'], 'title': e['title']}, audio)
                changes.append(f'{e["slug"]} 转写')

    # 6) 精读管线保活 + 立即上线
    ensure_watch()
    if changes and not DRY:
        deploy()

    git_commit_push('; '.join(changes) or '元数据')
    log(f'== sync done: {"; ".join(changes) if changes else "no new episodes"} ==')


if __name__ == '__main__':
    main()
