#!/usr/bin/env python3
"""品牌资产生成：站点图标（favicon / apple-touch / PWA）与分享卡片（Open Graph）。

图标为静态资产，只在设计变更时运行 `python3 tools/brand.py icons`，产物入库。
分享卡片随构建生成（build.py 调用 build_og），产物不入库；已存在且内容未变的卡片会跳过。
字体（OFL 授权）首次运行时下载到 tools/.cache/fonts/。
"""
import hashlib
import io
import json
import sys
import urllib.request
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont, ImageOps, ImageFilter

ROOT = Path(__file__).resolve().parent
SITE = ROOT.parent / 'site'
CACHE = ROOT / '.cache'
FONTS = {
    'caslon': ('LibreCaslonText.ttf', 'https://raw.githubusercontent.com/google/fonts/main/ofl/librecaslontext/LibreCaslonText%5Bwght%5D.ttf'),
    'serif_sc': ('NotoSerifSC.ttf', 'https://raw.githubusercontent.com/google/fonts/main/ofl/notoserifsc/NotoSerifSC%5Bwght%5D.ttf'),
}
_faces_p = ROOT / 'og-faces.json'
FACES = json.loads(_faces_p.read_text()) if _faces_p.exists() else {}
INK, PAPER, RED, MUTED = (17, 17, 17), (255, 255, 255), (179, 38, 30), (107, 107, 103)


def font_path(key):
    name, url = FONTS[key]
    p = CACHE / 'fonts' / name
    if not p.exists():
        p.parent.mkdir(parents=True, exist_ok=True)
        print(f'  下载字体 {name} …')
        urllib.request.urlretrieve(url, p)
    return p


def font(key, size, weight='Bold'):
    f = ImageFont.truetype(str(font_path(key)), size)
    try:
        f.set_variation_by_name(weight)
    except Exception:
        pass
    return f


# ---------------------------------------------------------------- 图标
def draw_mark(size, pad_ratio=0.0, radius_ratio=0.0):
    """黑底白色 Caslon「L」。按字形实际墨迹居中，再微调到视觉重心。"""
    s = size * 4  # 超采样，缩小时更锐利
    im = Image.new('RGB', (s, s), INK)
    if radius_ratio:
        mask = Image.new('L', (s, s), 0)
        ImageDraw.Draw(mask).rounded_rectangle([0, 0, s - 1, s - 1], radius=int(s * radius_ratio), fill=255)
        bg = Image.new('RGBA', (s, s), (0, 0, 0, 0))
        bg.paste(im, mask=mask)
        im = bg
    inner = s * (1 - 2 * pad_ratio)
    f = font('caslon', int(inner * 0.86), 'Bold')
    d = ImageDraw.Draw(im)
    l, t, r, b = d.textbbox((0, 0), 'L', font=f)
    w, h = r - l, b - t
    x = (s - w) / 2 - l + s * 0.012   # L 的墨迹偏左，稍向右推
    y = (s - h) / 2 - t - s * 0.004
    d.text((x, y), 'L', font=f, fill=PAPER)
    return im.resize((size, size), Image.LANCZOS)


def build_icons():
    out = SITE
    draw_mark(180).save(out / 'apple-touch-icon.png', optimize=True)
    for n in (192, 512):
        draw_mark(n, radius_ratio=0.0).save(out / f'icon-{n}.png', optimize=True)
    # maskable：留出安全区，系统裁成圆形 / 圆角时字母不被切
    draw_mark(512, pad_ratio=0.12).save(out / 'icon-maskable-512.png', optimize=True)
    ico = [draw_mark(n) for n in (16, 32, 48)]
    ico[2].save(out / 'favicon.ico', sizes=[(16, 16), (32, 32), (48, 48)], append_images=ico[:2])
    draw_mark(32).save(out / 'favicon-32.png', optimize=True)
    manifest = {
        'name': 'Lex Fridman 播客全访谈', 'short_name': 'Lex 中文',
        'description': 'Lex Fridman 播客全部单集：官方音频、视频、英文文稿与中文精读',
        'lang': 'zh-CN', 'start_url': '/', 'scope': '/', 'display': 'standalone',
        'background_color': '#ffffff', 'theme_color': '#ffffff',
        'icons': [
            {'src': '/icon-192.png', 'sizes': '192x192', 'type': 'image/png'},
            {'src': '/icon-512.png', 'sizes': '512x512', 'type': 'image/png'},
            {'src': '/icon-maskable-512.png', 'sizes': '512x512', 'type': 'image/png', 'purpose': 'maskable'},
        ],
    }
    (out / 'site.webmanifest').write_text(json.dumps(manifest, ensure_ascii=False, indent=2))
    print('icons: favicon.ico / favicon-32.png / apple-touch-icon.png / icon-192/512 / maskable / site.webmanifest')


# ---------------------------------------------------------------- 分享卡片
OG_W, OG_H = 1200, 630
OG_VERSION = 'nyer-9'
CLOSE = set('，。、：；！？）」』”’》〉】,.;:!?)]}%')


def tokens(text):
    """中文逐字、西文按词切分，便于按宽度断行。"""
    out, buf = [], ''
    for ch in text:
        if ord(ch) < 0x2E80 and not ch.isspace():
            buf += ch
            continue
        if buf:
            out.append(buf); buf = ''
        out.append(ch)
    if buf:
        out.append(buf)
    return out


def wrap(draw, text, f, width, max_lines):
    lines, cur = [], ''
    toks = tokens(text)
    i = 0
    while i < len(toks):
        t = toks[i]
        trial = cur + t
        if draw.textlength(trial, font=f) <= width or not cur.strip() or t in CLOSE:
            cur = trial  # 行首禁则：闭合标点悬挂在行尾
            i += 1
        else:
            # 优先在顿号、逗号、冒号、空格等处换行，避免把一个词拆到两行
            cut = max(cur.rfind(c) for c in '、，：；· ')
            if cut >= len(cur) * 0.5:
                lines.append(cur[:cut + 1].rstrip())
                cur = cur[cut + 1:].lstrip()
            else:
                lines.append(cur.rstrip()); cur = ''
            if t.isspace():
                i += 1
        if len(lines) == max_lines:
            break
    if cur and len(lines) < max_lines:
        lines.append(cur.rstrip())
    if i < len(toks) and lines:  # 截断加省略号
        last = lines[-1]
        while last and draw.textlength(last + '…', font=f) > width:
            last = last[:-1]
        lines[-1] = last.rstrip('，、：；') + '…'
    return lines


def wrap_balanced(draw, text, f, width, max_lines):
    """在行数相同的候选断行里挑最好看的：句中断词、末行孤字扣分，其次各行长短接近。"""
    BREAK = tuple('、，：；·》」』）') + (' ',)

    def score(ls):
        bad = sum(1 for ln in ls[:-1] if not ln.endswith(BREAK) and not ln[-1:].isascii())
        orphan = 2 if len(ls) > 1 and len(ls[-1].strip()) <= 2 else 0
        ws = [draw.textlength(ln, font=f) for ln in ls]
        return (bad + orphan, len(ls), max(ws) - min(ws))  # 先保证不拆词、无孤字，再求行少、行齐

    base = wrap(draw, text, f, width, max_lines)
    if len(base) < 2 or base[-1].endswith('…'):
        return base
    best, best_s = base, score(base)
    w = width
    while w > width * 0.55:
        w -= width * 0.02
        trial = wrap(draw, text, f, w, max_lines)
        if len(trial) > max_lines or trial[-1].endswith('…'):
            continue
        sc = score(trial)
        if sc < best_s:
            best, best_s = trial, sc
    return best


def yt_image(yid):
    p = CACHE / 'yt' / f'{yid}.jpg'
    if p.exists() and p.stat().st_size > 2000:
        return Image.open(p)
    p.parent.mkdir(parents=True, exist_ok=True)
    for q in ('maxresdefault', 'hqdefault'):
        try:
            data = urllib.request.urlopen(f'https://i.ytimg.com/vi/{yid}/{q}.jpg', timeout=20).read()
            if len(data) > 2000:
                p.write_bytes(data)
                return Image.open(io.BytesIO(data))
        except Exception:
            continue
    return None


def photo_panel(yid, w, h):
    im = yt_image(yid) if yid else None
    if im is None:
        return None
    im = im.convert('RGB')
    iw, ih = im.size
    if ih * 16 > iw * 9 + 8:  # hqdefault 是 4:3 加黑边，先裁回 16:9
        ch = iw * 9 // 16
        im = im.crop((0, (ih - ch) // 2, iw, (ih - ch) // 2 + ch))
        iw, ih = im.size
    # 放大 1.3 倍，以人脸常在的位置（横向 66%、纵向 42%）为中心裁竖幅，避开缩略图上的标题字与 ROUND 角标
    scale = h * 1.3 / ih
    im = im.resize((int(iw * scale), int(ih * scale)), Image.LANCZOS)
    cx, cy = FACES.get(yid) or (0.66, 0.42)  # 有预计算的人脸位置就以人脸为中心（tools/og_faces.py）
    cy = min(cy + 0.06, 0.6)  # 人脸略偏上，留出下巴与肩
    x0 = min(max(0, int(im.width * cx - w / 2)), im.width - w)
    y0 = min(max(0, int(im.height * cy - h / 2)), im.height - h)
    im = im.crop((x0, y0, x0 + w, y0 + h))
    im = ImageOps.grayscale(im)
    im = ImageOps.autocontrast(im, cutoff=1)
    return im.convert('RGB')


def og_card(x, total=None, n_zh=None):
    """x 为 None 时生成站点默认卡片。"""
    im = Image.new('RGB', (OG_W, OG_H), PAPER)
    d = ImageDraw.Draw(im)
    if x is None:
        f_title = font('caslon', 104, 'Bold')
        f_zh = font('serif_sc', 66, 'Bold')
        f_sub = font('serif_sc', 26, 'Medium')
        t1, t2 = 'Lex Fridman', '播客全访谈'
        w1, w2 = d.textlength(t1, font=f_title), d.textlength(t2, font=f_zh)
        gap = 26
        x0 = (OG_W - (w1 + gap + w2)) / 2
        base = 312
        d.text((OG_W / 2, 168), '中 文 精 读  ·  官 方 音 频  ·  双 语 文 稿', font=font('serif_sc', 22, 'SemiBold'), fill=RED, anchor='mm')
        d.text((x0, base), t1, font=f_title, fill=INK, anchor='ls')
        d.text((x0 + w1 + gap, base), t2, font=f_zh, fill=INK, anchor='ls')
        y = base + 46
        d.rectangle([110, y, OG_W - 110, y + 5], fill=INK)
        d.rectangle([110, y + 11, OG_W - 110, y + 12], fill=INK)
        sub = f'{total} 期深度访谈  ·  {n_zh} 篇中文长文  ·  2018 年至今'
        d.text((OG_W / 2, y + 72), sub, font=f_sub, fill=MUTED, anchor='mm')
        d.text((OG_W / 2, OG_H - 60), 'lex.qiaomu.ai', font=font('caslon', 26, 'Regular'), fill=MUTED, anchor='mm')
        return im
    panel_w = 470
    ph = photo_panel(x.get('y'), panel_w, OG_H)
    text_w = OG_W - (panel_w if ph else 0) - 150
    if ph:
        # 照片左缘由白渐隐，与纸面自然衔接，同时盖住缩略图边缘残留的标题字
        fade = 120
        grad = ImageOps.mirror(Image.linear_gradient('L').rotate(90)).resize((fade, OG_H))  # 左 255 → 右 0
        white = Image.new('RGB', (fade, OG_H), PAPER)
        ph.paste(white, (0, 0), grad)
        im.paste(ph, (OG_W - panel_w, 0))
    L = 80
    f_k = font('serif_sc', 24, 'SemiBold')
    kicker = ('中文精读  ·  ' if x.get('r') else '') + (f'第 {x["n"]} 期' if x.get('n') is not None else '特别节目')
    zh = x['zh_t']
    size = (60 if len(zh) <= 30 else 52 if len(zh) <= 42 else 46) if ph else (68 if len(zh) <= 26 else 58)
    f_t = font('serif_sc', size, 'Bold')
    lines = wrap_balanced(d, zh, f_t, text_w, 4)
    en = x['en_t'] if x['en_t'] and x['en_t'] != zh else ''
    f_en = font('caslon', 25, 'Regular')
    en_lines = wrap(d, en, f_en, text_w, 2) if en else []
    lh = int(size * 1.36)
    block = 36 + 22 + len(lines) * lh + (22 + len(en_lines) * 36 if en_lines else 0)
    top, bottom = 56, OG_H - 96 - 30
    y0 = top + max(0, (bottom - top - block) // 2)
    d.text((L, y0), kicker, font=f_k, fill=RED if x.get('r') else MUTED)
    y = y0 + 36 + 22
    for ln in lines:
        d.text((L, y), ln, font=f_t, fill=INK)
        y += lh
    y += 22 - 36
    for ln in en_lines:
        y += 36
        d.text((L, y), ln, font=f_en, fill=MUTED)
    # 底部落款：粗细双线 + 站名
    by = OG_H - 96
    d.rectangle([L, by, L + text_w, by + 3], fill=INK)
    d.rectangle([L, by + 8, L + text_w, by + 8], fill=INK)
    d.text((L, by + 42), 'Lex Fridman', font=font('caslon', 28, 'Bold'), fill=INK, anchor='lm')
    d.text((L + d.textlength('Lex Fridman ', font=font('caslon', 28, 'Bold')), by + 42), '播客全访谈',
           font=font('serif_sc', 25, 'SemiBold'), fill=INK, anchor='lm')
    d.text((L + text_w, by + 42), 'lex.qiaomu.ai', font=font('caslon', 22, 'Regular'), fill=MUTED, anchor='rm')
    return im


def build_og(eps, strip_no):
    """为每期生成 /og/{slug}.jpg，并生成站点默认 /og/default.jpg。内容未变则跳过。"""
    from concurrent.futures import ThreadPoolExecutor
    out = SITE / 'og'
    out.mkdir(exist_ok=True)
    state_p = CACHE / 'og-state.json'
    state = json.loads(state_p.read_text()) if state_p.exists() else {}
    total, n_zh = len(eps), sum(1 for x in eps if x.get('r'))
    jobs = []
    for x in eps:
        item = dict(x, zh_t=strip_no(x.get('zh')) or strip_no(x['t']), en_t=strip_no(x['t']))
        key = hashlib.md5(json.dumps([OG_VERSION, item['zh_t'], item['en_t'], x.get('n'), x.get('y'), x.get('r')],
                                     ensure_ascii=False).encode()).hexdigest()
        if state.get(x['s']) != key or not (out / f'{x["s"]}.jpg').exists():
            jobs.append((item, key))
    dkey = f'{OG_VERSION}-{total}-{n_zh}'
    if state.get('__default') != dkey or not (out / 'default.jpg').exists():
        og_card(None, total, n_zh).save(out / 'default.jpg', quality=86, optimize=True, progressive=True)
        state['__default'] = dkey
    # 先并发拉缩略图，再串行渲染（PIL 字体对象非线程安全）
    with ThreadPoolExecutor(16) as ex:
        list(ex.map(lambda j: j[0].get('y') and yt_image(j[0]['y']), jobs))
    for item, key in jobs:
        og_card(item).save(out / f'{item["s"]}.jpg', quality=84, optimize=True, progressive=True)
        state[item['s']] = key
    state_p.write_text(json.dumps(state))
    print(f'og cards: {len(jobs)} rendered, {len(eps) - len(jobs)} cached')


if __name__ == '__main__':
    if 'icons' in sys.argv[1:]:
        build_icons()
