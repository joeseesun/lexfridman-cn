#!/usr/bin/env python3
"""lex.qiaomu.ai 静态站构建器。

输入：
  tools/lex-master.json      主数据（506 期）
  tools/feed_audio.json      官方 RSS 音频直链（by_num / by_slug）
  tools/translations.json    LLM 翻译的中文标题/嘉宾/简介（可缺）
  tools/official/{slug}.txt  官方文稿正文
  site/transcripts/{slug}.txt Kaggle 存档 + ASR 文稿
  site/zh/{slug}.html        中文精读片段
  site/data/zh-index.json    中文精读索引

输出：
  site/ep/{slug}/index.html  506 个自包含单集页（可被搜索引擎直接抓取）
  site/data/episodes.json    首页数据（含中英双语标题）
  site/sitemap.xml           首页 + 506 个单集 URL
  site/llms.txt              AI 爬虫（GEO）索引

断点续跑安全：可重复执行；ASR 批次补完后重跑即可覆盖更新。
"""
import html as H
import json
import re
import shutil
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent
SITE = ROOT.parent / 'site'
DOMAIN = 'https://lex.qiaomu.ai'
TODAY = date.today().isoformat()

CSS_V, APP_V, EP_V = 9, 8, 4

THEME_SCRIPT = """<script>
(function () {
  var t = null;
  try { t = localStorage.getItem('lex-theme'); } catch (e) {}
  if (t !== 'light' && t !== 'dark') {
    t = (window.matchMedia && window.matchMedia('(prefers-color-scheme: light)').matches) ? 'light' : 'dark';
  }
  document.documentElement.setAttribute('data-theme', t);
  var meta = document.querySelector('meta[name="theme-color"]');
  function syncMeta() { if (meta) meta.content = t === 'light' ? '#f7f7f8' : '#0d0d0f'; }
  syncMeta();
  window.__lexTheme = t;
  window.__lexThemeToggle = function () {
    t = t === 'light' ? 'dark' : 'light';
    try { localStorage.setItem('lex-theme', t); } catch (e) {}
    document.documentElement.setAttribute('data-theme', t);
    syncMeta();
  };
  document.addEventListener('click', function (e) {
    if (e.target.closest && e.target.closest('[data-theme-toggle]')) window.__lexThemeToggle();
  });
})();
</script>"""

THEME_BTN = ('<button class="theme-toggle" data-theme-toggle aria-label="切换浅色 / 深色模式" '
             'title="切换浅色 / 深色模式"><span class="i-sun">☀</span><span class="i-moon">☾</span></button>')

FEED_LINK = (f'<link rel="alternate" type="application/rss+xml" '
             f'title="Lex Fridman 播客全访谈 · 中文精读全文" href="{DOMAIN}/feed.xml">')

FOOTER_FEED = ('<p class="footer-feed">订阅本站更新：<a href="/feed.xml">RSS 全文订阅</a>'
               '（中文精读全文 + 官方音频） '
               '<button class="copy-feed" type="button" data-copy-feed>复制地址</button></p>')

master = json.load(open(ROOT / 'lex-master.json'))
feed = json.load(open(ROOT / 'feed_audio.json'))
trans = json.load(open(ROOT / 'translations.json')) if (ROOT / 'translations.json').exists() else {}
zh_index = json.load(open(SITE / 'data' / 'zh-index.json'))
ZH = set(zh_index.get('slugs', []))

kg_slugs = {e['slug'] for e in master if e.get('kaggleText')}
official = {p.stem for p in (ROOT / 'official').glob('*.txt')}
site_txt = {p.stem for p in (SITE / 'transcripts').glob('*.txt')}
asr_slugs = {s for s in site_txt - kg_slugs - official if not s.startswith('hs_')}


def text_for(slug):
    """返回 (source_tag, text)；官方 > Kaggle 存档 > ASR。"""
    if slug in official:
        return 'ot', (ROOT / 'official' / f'{slug}.txt').read_text()
    if slug in kg_slugs and slug in site_txt:
        return 'kg', (SITE / 'transcripts' / f'{slug}.txt').read_text()
    if slug in asr_slugs:
        return 'asr', (SITE / 'transcripts' / f'{slug}.txt').read_text()
    return None, None


TR_SOURCE_NOTE = {
    'ot': '文稿来自 Lex Fridman 官网公开发布的官方 Transcript（含说话人与时间戳）。',
    'kg': '文稿来自公开 Kaggle 数据集（rajneesh231/lex-fridman-podcast-transcript），为早期自动转录存档，可能存在识别错误。',
    'asr': '文稿由本站用语音识别模型（基于官方发布音频）机器转写，可能有识别错误，人名与数字请以音频为准。',
}


def fmt_date(d):
    if not d:
        return ''
    return f'{d[:4]} 年 {int(d[5:7])} 月'


def parse_orig(t):
    m = re.match(r'^#(\d+)\s*[–—-]\s*(.+)$', t or '')
    if m:
        return int(m.group(1)), m.group(2)
    return None, t or ''


def audio_for(e):
    if e.get('num') is not None and str(e['num']) in feed['by_num']:
        return feed['by_num'][str(e['num'])]
    return feed['by_slug'].get(e['slug'])


def norm_zh(zh):
    """#486 – 迈克尔·莱文 → #486 迈克尔·莱文（统一期号后不带破折号）"""
    return re.sub(r'^(#\d+)\s*[–—-]\s*', r'\1 ', zh or '')


def build_data():
    eps = []
    for e in master:
        tag, _ = text_for(e['slug'])
        eps.append({
            'n': e.get('num'), 't': e['title'], 's': e['slug'], 'd': e.get('date'),
            'y': e.get('ytId'),
            'zh': trans.get(e['slug'], {}).get('zh'),
            'guest': trans.get(e['slug'], {}).get('guest'),
            'tr': tag, 'au': bool(audio_for(e)),
        })
    out = {'updated': TODAY, 'episodes': eps}
    (SITE / 'data' / 'episodes.json').write_text(json.dumps(out, ensure_ascii=False, separators=(',', ':')))
    print(f"episodes.json: {len(eps)} eps, "
          f"tr={sum(1 for x in eps if x['tr'])}, zh={len(ZH)}, au={sum(1 for x in eps if x['au'])}, "
          f"zh_title={sum(1 for x in eps if x['zh'])}")
    return eps


EP_SHELL = """<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<meta name="color-scheme" content="dark light">
<meta name="theme-color" content="#0d0d0f">
<title>{title_tag}</title>
<meta name="description" content="{desc}">
<link rel="canonical" href="{url}/">
<meta property="og:title" content="{og_title}">
<meta property="og:description" content="{desc}">
<meta property="og:type" content="article">
<meta property="og:url" content="{url}/">
<meta property="og:image" content="{og_img}">
<meta property="og:site_name" content="Lex Fridman 播客全访谈">
<meta name="twitter:card" content="summary_large_image">
<script type="application/ld+json">{ldjson}</script>
{theme_script}
{feed_link}
<link rel="stylesheet" href="/style.css?v={css_v}">
</head>
<body>
<a class="skip-link" href="#main">跳到主要内容</a>
<header class="site-header">
  <div class="wrap header-inner">
    <div class="brand">
      <h1><a href="/">Lex Fridman 播客全访谈</a></h1>
      <p class="tagline">视频 · 音频 · 双语文稿 · 中文精读</p>
    </div>
    <div class="header-actions"><a class="back-all" href="/">← 返回全部单集</a>{theme_btn}</div>
  </div>
</header>

<main class="wrap ep-main" id="main">
  <nav class="crumbs" aria-label="面包屑"><a href="/">首页</a><span>/</span><span>{crumb}</span></nav>
  <article class="ep">
    <h1 class="ep-title">{h1}</h1>
    {orig_line}
    <div class="ep-meta">
      {ep_no}<span>{date_disp}</span>{guest_span}{badges}
    </div>
    {audio_html}
    {video_html}
    <section class="content-tabs">
      {tab_buttons}
      {panel_zh}
      {panel_tr}
      {no_tr_note}
    </section>
    {resources}
    <nav class="ep-prevnext">
      {prevnext}
    </nav>
  </article>
</main>

<footer class="site-footer">
  <div class="wrap footer-inner">
    <div class="footer-note">
      <p>非官方粉丝站点，与 Lex Fridman 及节目制作方无隶属关系。音频、视频与原始文稿版权归原权利方所有，本站不托管任何媒体文件。中文精读由 AI 改写生成，仅供学习参考，建议收听<a href="{lex}" target="_blank" rel="noopener">原始访谈</a>。详见<a href="/disclaimer/">免责声明</a>。</p>
      {footer_feed}
      <p class="footer-links">
        <a href="https://tuijian.qiaomu.ai/" target="_blank" rel="noopener">乔木推荐</a>
        <a href="https://github.com/joeseesun/" target="_blank" rel="noopener">GitHub</a>
        <a href="https://x.com/vista8" target="_blank" rel="noopener">X</a>
      </p>
    </div>
  </div>
</footer>

<script defer src="https://umami.qiaomu.ai/script.js" data-website-id="572fd127-0eb0-4566-8ed6-df70b531ab01" data-domains="lex.qiaomu.ai"></script>
<script src="/ep.js?v={ep_v}"></script>
</body>
</html>
"""


def badges_html(tr, zh):
    b = []
    if zh:
        b.append('<span class="badge zh">中文精读</span>')
    if tr:
        b.append('<span class="badge">文稿</span>')
    return f'<span class="badges">{"".join(b)}</span>' if b else ''


def build_page(i, eps):
    e = master[i]
    slug, num, title = e['slug'], e.get('num'), e['title']
    d = e.get('date') or ''
    lex = e.get('lexUrl') or (f'https://lexfridman.com/{slug}/' if num else 'https://lexfridman.com/podcast/')
    ot = e.get('officialTranscript')
    hs = e.get('hsUrl')
    y = e.get('ytId')
    audio = audio_for(e)
    tr_tag, tr_text = text_for(slug)
    zh_html_file = SITE / 'zh' / f'{slug}.html'
    has_zh = slug in ZH and zh_html_file.exists()
    tr_info = trans.get(slug, {})
    zh_title = norm_zh(tr_info.get('zh'))
    guest, desc = tr_info.get('guest'), tr_info.get('desc')
    lede = desc

    url = f'{DOMAIN}/ep/{slug}'
    title_tag = f'{zh_title} | Lex Fridman 播客第 {num} 期' if (zh_title and num) else \
        (f'{zh_title} | Lex Fridman 播客' if zh_title else f'{title} | Lex Fridman 播客')
    desc = desc or f'Lex Fridman 与嘉宾的深度访谈：{title[:80]}'
    desc = f'{desc} 含官方音频、视频与英文文稿。'
    og_title = f'{zh_title}｜{title}' if zh_title else title

    ld_media = []
    if audio:
        ld_media.append({"@type": "AudioObject", "contentUrl": audio, "encodingFormat": "audio/mpeg"})
    if y:
        ld_media.append({"@type": "VideoObject", "embedUrl": f'https://www.youtube.com/embed/{y}'})
    ld = {"@context": "https://schema.org", "@graph": [
        {"@type": "PodcastEpisode", "@id": f'{url}/#episode', "url": f'{url}/',
         "name": title_tag, "alternativeHeadline": title, "description": desc.rstrip('。 含官方音频、视频与英文文稿。'),
         "datePublished": d or None, "episodeNumber": num, "inLanguage": "en",
         "partOfSeries": {"@type": "PodcastSeries", "name": "Lex Fridman Podcast",
                          "url": "https://lexfridman.com/podcast/"},
         "associatedMedia": ld_media},
        {"@type": "BreadcrumbList", "itemListElement": [
            {"@type": "ListItem", "position": 1, "name": "首页", "item": f'{DOMAIN}/'},
            {"@type": "ListItem", "position": 2, "name": title_tag.split(' | ')[0], "item": f'{url}/'}]},
    ]}
    # <script> 内是 raw text，不做 HTML 转义；只防 </script> 逃逸
    ldjson = json.dumps(ld, ensure_ascii=False).replace('<', '\\u003c')

    h1 = H.escape(zh_title) if zh_title else H.escape(title)
    orig_line = (f'<p class="ep-title-en">{H.escape(title)}</p>' if zh_title and title != zh_title else '')
    ep_no = f'<span class="ep-no">第 {num} 期</span><span class="dot">·</span>' if num else ''
    date_disp = f'<time datetime="{d}">{fmt_date(d)}</time><span class="dot">·</span>' if d else ''
    guest_span = f'<span>嘉宾 / 主题：{H.escape(guest)}</span><span class="dot">·</span>' if guest else ''

    audio_html = ''
    if audio:
        audio_html = (f'<div class="audio-player" data-slug="{H.escape(slug)}" data-title="{H.escape(zh_title or title)}">'
                      f'<audio src="{H.escape(audio)}" preload="none"></audio>'
                      f'<button class="ap-play" aria-label="播放">▶</button>'
                      f'<div class="ap-mid">'
                      f'<div class="ap-line1"><span class="ap-label">官方音频</span>'
                      f'<span class="ap-time"><span class="ap-cur">00:00</span> / <span class="ap-dur">--:--</span></span></div>'
                      f'<div class="ap-bar" role="slider" aria-label="播放进度" tabindex="0">'
                      f'<div class="ap-buf"></div><div class="ap-fill"></div></div>'
                      f'<div class="ap-line2">'
                      f'<button class="ap-skip" data-s="-15">−15s</button>'
                      f'<button class="ap-skip" data-s="15">+15s</button>'
                      f'<button class="ap-rate">1×</button>'
                      f'<span class="ap-resume" hidden>已从上次位置继续 · <button class="ap-restart">从头听</button></span>'
                      f'</div></div></div>')

    video_html = ''
    if y:
        img = f'https://i.ytimg.com/vi/{y}/hqdefault.jpg'
        video_html = (f'<div class="video-facade" data-yt="{H.escape(y)}" tabindex="0" role="button" aria-label="播放视频">'
                      f'<img loading="lazy" src="{img}" alt="{H.escape(zh_title or title)}">'
                      f'<span class="vf-play">▶ 播放视频</span></div>')
    elif audio:
        video_html = '<div class="ep-notice">该期暂无视频，可直接收听上方官方音频。</div>'
    else:
        video_html = '<div class="ep-notice">该期暂无音视频存档，可通过下方资源访问原始页面。</div>'

    tab_buttons = ['<div class="tabs" role="tablist">']
    if has_zh:
        tab_buttons.append('<button class="tab-btn" data-tab="zh" role="tab">中文精读</button>')
    if tr_tag:
        tab_buttons.append('<button class="tab-btn" data-tab="tr" role="tab">英文文稿</button>')
    tab_buttons.append('</div>')
    tab_buttons = ''.join(tab_buttons) if (has_zh or tr_tag) else ''

    panel_zh = ''
    if has_zh:
        lede_html = f'<p class="zh-lede">{H.escape(lede)}</p>' if lede else ''
        panel_zh = (f'<div class="tab-panel" id="panel-zh" data-panel="zh">'
                    f'<div class="zh-note">中文精读由 AI 基于原始访谈改写，非官方翻译，可能存在偏差或错误；表述以原音频与官方文稿为准。<a href="/disclaimer/">说明</a></div>'
                    f'{lede_html}'
                    f'<div class="zh-article">{zh_html_file.read_text()}</div></div>')

    panel_tr = ''
    if tr_tag:
        panel_tr = (f'<div class="tab-panel" id="panel-tr" data-panel="tr">'
                    f'<div class="tr-note">{TR_SOURCE_NOTE[tr_tag]}</div>'
                    f'<div class="transcript-text">{H.escape(tr_text)}</div></div>')

    no_tr_note = ''
    if not has_zh and not tr_tag:
        links = []
        if ot:
            links.append(f'<a href="{H.escape(ot)}" target="_blank" rel="noopener">官方 Transcript</a>')
        if hs:
            links.append(f'<a href="{H.escape(hs)}" target="_blank" rel="noopener">HappyScribe 文稿</a>')
        parts = ['该期文稿暂未收录。']
        if links:
            parts.append('外部文稿：' + ' · '.join(links) + '。')
        if audio or y:
            parts.append('可直接收听上方音频或观看视频。')
        no_tr_note = f'<div class="ep-notice">{"".join(parts)}</div>'

    res = ['<section class="ep-resources"><h2>本集资源与出处</h2><ul>']
    if y:
        res.append(f'<li><span class="res-k">视频</span><a href="https://www.youtube.com/watch?v={H.escape(y)}" target="_blank" rel="noopener">在 YouTube 收看</a></li>')
    if audio:
        res.append(f'<li><span class="res-k">音频</span><a href="{H.escape(audio)}" target="_blank" rel="noopener">官方 MP3 直链</a><span class="res-sub">来自 lexfridman.com 官方播客 RSS</span></li>')
    if lex:
        res.append(f'<li><span class="res-k">官网</span><a href="{H.escape(lex)}" target="_blank" rel="noopener">Lex Fridman 官网本集页面</a></li>')
    if ot:
        res.append(f'<li><span class="res-k">文稿</span><a href="{H.escape(ot)}" target="_blank" rel="noopener">官方 Transcript（lexfridman.com）</a></li>')
    if hs:
        res.append(f'<li><span class="res-k">文稿</span><a href="{H.escape(hs)}" target="_blank" rel="noopener">HappyScribe 版文稿</a></li>')
    if tr_tag in ('kg', 'asr'):
        res.append(f'<li><span class="res-k">文稿</span><a href="/transcripts/{H.escape(slug)}.txt" target="_blank" rel="noopener">本站纯文本版</a></li>')
    res.append('</ul></section>')
    resources = ''.join(res)

    prev_e, next_e = (eps[i - 1] if i > 0 else None), (eps[i + 1] if i < len(eps) - 1 else None)

    def pn_link(ne, label):
        if not ne:
            return '<span></span>'
        t = ne['zh'] or ne['t']
        m = re.match(r'^#(\d+)\s*[–—-]?\s*(.*)$', t)
        txt = f'#{ne["n"]} {m.group(2)}' if (ne['n'] and m) else t
        short = (txt[:26] + '…') if len(txt) > 27 else txt
        return f'<a href="/ep/{ne["s"]}/">{label} {H.escape(short)}</a>'

    prevnext = f'{pn_link(prev_e, "← 上一期")}{pn_link(next_e, "下一期 →")}'

    crumb = f'第 {num} 期' if num else H.escape(title[:20])
    page = EP_SHELL.format(
        title_tag=H.escape(title_tag), desc=H.escape(desc), url=url,
        og_title=H.escape(og_title), og_img=f'https://i.ytimg.com/vi/{y}/hqdefault.jpg' if y else f'{DOMAIN}/assets/og-default.png',
        ldjson=ldjson, css_v=CSS_V, ep_v=EP_V,
        theme_script=THEME_SCRIPT, theme_btn=THEME_BTN,
        feed_link=FEED_LINK, footer_feed=FOOTER_FEED,
        crumb=crumb, h1=h1, orig_line=orig_line, ep_no=ep_no, date_disp=date_disp,
        guest_span=guest_span, badges=badges_html(tr_tag, has_zh),
        audio_html=audio_html, video_html=video_html, tab_buttons=tab_buttons,
        panel_zh=panel_zh, panel_tr=panel_tr, no_tr_note=no_tr_note,
        resources=resources, prevnext=prevnext, lex=H.escape(lex),
    )
    dest = SITE / 'ep' / slug / 'index.html'
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(page)


def build_sitemap(eps):
    lines = ['<?xml version="1.0" encoding="UTF-8"?>',
             '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">',
             f'<url><loc>{DOMAIN}/</loc><lastmod>{TODAY}</lastmod><priority>1.0</priority></url>',
             f'<url><loc>{DOMAIN}/disclaimer/</loc><lastmod>{TODAY}</lastmod><priority>0.3</priority></url>']
    for x in eps:
        lm = x['d'] or TODAY
        lines.append(f'<url><loc>{DOMAIN}/ep/{x["s"]}/</loc><lastmod>{lm}</lastmod><priority>0.8</priority></url>')
    lines.append('</urlset>')
    (SITE / 'sitemap.xml').write_text('\n'.join(lines))
    print(f'sitemap.xml: {len(eps) + 2} urls')


DISCLAIMER_BODY = """
    <nav class="crumbs" aria-label="面包屑"><a href="/">首页</a><span>/</span><span>免责声明</span></nav>
    <article class="ep">
      <h1 class="ep-title">免责声明与内容说明</h1>
      <div class="zh-article disclaimer-body">
        <p>本站（lex.qiaomu.ai）是一个非官方的中文导读与检索项目，帮助中文读者发现并理解 Lex Fridman Podcast。本站与 Lex Fridman、节目制作方及任何嘉宾均无隶属或合作关系，站点内容不代表其观点或立场。</p>

        <h2>内容版权</h2>
        <p>本站所涉全部原始内容——包括音频、视频、原始文字稿、标题与节目名称——的版权归 Lex Fridman 及相应嘉宾、制作方所有。本站不托管、不存储、不分发任何媒体文件：音频通过官方播客 RSS 发布渠道（blubrry）在线播放；视频与原始文稿均以链接方式指向官方页面或公开来源。对原始内容本身，本站仅作必要限度的引用与出处标注。</p>

        <h2>中文精读</h2>
        <p>「中文精读」由 AI 基于原始访谈内容辅助生成的中文解读，属于二次创作，并非官方翻译，也未经 Lex Fridman 或嘉宾审阅。受语言理解与信息压缩所限，可能存在理解偏差、遗漏或错误，不构成对原意的权威解释。请以官方发布的原始音频与文字稿为准；如本站表述与原始内容存在出入，以原始内容为准。</p>

        <h2>英文文稿来源</h2>
        <p>单集页的英文文稿分三类，并在每页文稿区内标注来源：</p>
        <ul>
          <li>官方 Transcript——来自 lexfridman.com 公开发布；</li>
          <li>Kaggle 公开数据集存档——为早期自动转录，可能存在识别错误；</li>
          <li>机器转写——本站基于官方发布音频用语音识别模型生成，可能有识别错误，人名与数字请以音频为准。</li>
        </ul>

        <h2>使用目的</h2>
        <p>本站为非商业性质，无广告、无收费，仅用于学习、检索与导读。如权利方认为本站任何内容（包括精读文字、文稿片段或页面呈现方式）不适合展示，请联系站点维护者，经确认后将移除或更正。</p>

        <h2>反馈与联系</h2>
        <p>纠错、建议或版权事宜，可通过 <a href="https://x.com/vista8" target="_blank" rel="noopener">X（@vista8）</a> 或 <a href="https://github.com/joeseesun/" target="_blank" rel="noopener">GitHub</a> 联系站点维护者。</p>
      </div>
    </article>
"""


def build_disclaimer():
    body = DISCLAIMER_BODY
    title = '免责声明与内容说明 · Lex Fridman 播客全访谈'
    desc = '本站性质、内容版权归属、中文精读与文稿来源说明，以及反馈与移除流程。'
    url = f'{DOMAIN}/disclaimer'
    html = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<meta name="color-scheme" content="dark light">
<meta name="theme-color" content="#0d0d0f">
<title>{H.escape(title)}</title>
<meta name="description" content="{H.escape(desc)}">
<link rel="canonical" href="{url}/">
<meta property="og:title" content="{H.escape(title)}">
<meta property="og:description" content="{H.escape(desc)}">
<meta property="og:type" content="article">
<meta property="og:url" content="{url}/">
<meta property="og:site_name" content="Lex Fridman 播客全访谈">
{THEME_SCRIPT}
{FEED_LINK}
<link rel="stylesheet" href="/style.css?v={CSS_V}">
</head>
<body>
<a class="skip-link" href="#main">跳到主要内容</a>
<header class="site-header">
  <div class="wrap header-inner">
    <div class="brand">
      <h1><a href="/">Lex Fridman 播客全访谈</a></h1>
      <p class="tagline">视频 · 音频 · 双语文稿 · 中文精读</p>
    </div>
    <div class="header-actions"><a class="back-all" href="/">← 返回全部单集</a>{THEME_BTN}</div>
  </div>
</header>

<main class="wrap ep-main" id="main">{body}
  <nav class="ep-prevnext">
    <span></span><a href="/">← 返回全部单集</a>
  </nav>
</main>

<footer class="site-footer">
  <div class="wrap footer-inner">
    <div class="footer-note">
      <p>非官方粉丝站点，与 Lex Fridman 及节目制作方无隶属关系。音频、视频与原始文稿版权归原权利方所有，本站不托管任何媒体文件。中文精读由 AI 改写生成，仅供学习参考。详见<a href="/disclaimer/">免责声明</a>。</p>
      {FOOTER_FEED}
      <p class="footer-links">
        <a href="https://tuijian.qiaomu.ai/" target="_blank" rel="noopener">乔木推荐</a>
        <a href="https://github.com/joeseesun/" target="_blank" rel="noopener">GitHub</a>
        <a href="https://x.com/vista8" target="_blank" rel="noopener">X</a>
      </p>
    </div>
  </div>
</footer>

<script defer src="https://umami.qiaomu.ai/script.js" data-website-id="572fd127-0eb0-4566-8ed6-df70b531ab01" data-domains="lex.qiaomu.ai"></script>
<script src="/app.js?v={APP_V}"></script>
</body>
</html>
"""
    out = SITE / 'disclaimer' / 'index.html'
    out.parent.mkdir(exist_ok=True)
    out.write_text(html)
    print('disclaimer page: ok')


def build_llms(eps):
    lines = [f'# Lex Fridman 播客全访谈（lex.qiaomu.ai）', '',
             f'> Lex Fridman 播客 {len(eps)} 期中文导航站（非官方粉丝站点）：每期一个独立页面，含官方音频直链、'
             f'YouTube 视频、英文文稿（官方 Transcript / 公开数据集存档 / 机器转写）与 AI 改写的中文精读。'
             f'内容版权归 Lex Fridman 及嘉宾所有。', '',
             '## 中文精读（AI 深度改写）', '']
    for x in eps:
        if x['s'] in ZH:
            t = x['zh'] or x['t']
            lines.append(f'- [{t}]({DOMAIN}/ep/{x["s"]}/)：{(trans.get(x["s"], {}) or {}).get("desc", "")}')
    lines += ['', '## 全部单集索引', '']
    for x in eps:
        t = x['zh'] or x['t']
        orig = '' if not x['zh'] else f'（原标题：{x["t"]}）'
        d = trans.get(x['s'], {}) or {}
        desc = f'：{d["desc"]}' if d.get('desc') else ''
        lines.append(f'- [{t}]({DOMAIN}/ep/{x["s"]}/){desc}{orig}')
    (SITE / 'llms.txt').write_text('\n'.join(lines))
    print(f'llms.txt: {len(lines)} lines')


def cdata(s):
    return '<![CDATA[' + s.replace(']]>', ']]]]><![CDATA[>') + ']]>'


def rfc822(d):
    import datetime
    import email.utils
    try:
        dt = datetime.datetime.fromisoformat(d).replace(tzinfo=datetime.timezone.utc)
    except (ValueError, TypeError):
        dt = datetime.datetime.now(datetime.timezone.utc)
    return email.utils.format_datetime(dt)


def audio_len(url):
    """enclosure 的 Content-Length（HEAD，带 UA；Range 兜底），结果缓存 tools/audio_sizes.json。拿不到返回 0（RSS 规范允许）。"""
    import urllib.request
    cache = ROOT / 'audio_sizes.json'
    try:
        sizes = json.load(open(cache)) if cache.exists() else {}
    except Exception:
        sizes = {}
    if url not in sizes:
        sizes[url] = 0
        try:
            req = urllib.request.Request(url, method='HEAD',
                                         headers={'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)'})
            with urllib.request.urlopen(req, timeout=8) as r:
                sizes[url] = int(r.headers.get('Content-Length') or 0)
            if not sizes[url]:
                req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0', 'Range': 'bytes=0-0'})
                with urllib.request.urlopen(req, timeout=8) as r:
                    cr = r.headers.get('Content-Range') or ''
                    if '/' in cr:
                        sizes[url] = int(cr.rsplit('/', 1)[1] or 0)
        except Exception:
            pass
        try:
            json.dump(sizes, open(cache, 'w'))
        except Exception:
            pass
    return sizes.get(url) or 0


def build_feed(eps, limit=20):
    """RSS 2.0 全文订阅：最新 limit 期；有精读给全文，无精读只放简介与原文链接（不塞文稿节选，控制体积）。"""
    import html as HH
    import datetime
    import email.utils
    au_map = {}
    for e in master:
        au_map[e['slug']] = audio_for(e)
    items = []
    for x in sorted((e for e in eps if e['n'] is not None), key=lambda e: -e['n'])[:limit]:
        slug, num = x['s'], x['n']
        title = norm_zh(x['zh'] or x['t'])
        if not title.startswith('#'):
            title = f'#{num} {title}'
        url = f'{DOMAIN}/ep/{slug}/'
        d = trans.get(slug, {}) or {}
        desc = d.get('desc') or f'Lex Fridman 第 {num} 期访谈中文精读。'
        zh_file = SITE / 'zh' / f'{slug}.html'
        if zh_file.exists():
            body = zh_file.read_text() + (
                f'<hr><p>本文为中文精读（AI 基于原始访谈改写，仅供参考）。'
                f'收听原始音频、观看视频与阅读英文文稿请访问 <a href="{url}">原文页面</a>。</p>')
        else:
            body = ''
        au = au_map.get(slug)
        enc = (f'<enclosure url="{HH.escape(au)}" type="audio/mpeg" length="{audio_len(au)}"/>'
               if au else '')
        content = f'<content:encoded>{cdata(body)}</content:encoded>' if body else ''
        items.append(
            f'<item><title>{HH.escape(title)}</title>'
            f'<link>{url}</link>'
            f'<guid isPermaLink="true">{url}</guid>'
            f'<pubDate>{rfc822(x["d"])}</pubDate>'
            f'<description>{cdata(HH.escape(desc))}</description>'
            f'{content}'
            f'{enc}</item>')
    xml = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<rss version="2.0" xmlns:content="http://purl.org/rss/1.0/modules/content/" '
        'xmlns:atom="http://www.w3.org/2005/Atom">\n<channel>\n'
        f'<title>Lex Fridman 播客全访谈 · 中文精读</title>\n'
        f'<link>{DOMAIN}/</link>\n'
        f'<atom:link href="{DOMAIN}/feed.xml" rel="self" type="application/rss+xml"/>\n'
        f'<description>Lex Fridman 播客 {len(eps)} 期的中文精读全文、官方音频与文稿导航（非官方粉丝站点）</description>\n'
        '<language>zh-CN</language>\n'
        f'<lastBuildDate>{email.utils.format_datetime(datetime.datetime.now(datetime.timezone.utc))}</lastBuildDate>\n'
        '<generator>lex.qiaomu.ai static build</generator>\n'
        + '\n'.join(items) + '\n</channel>\n</rss>\n')
    (SITE / 'feed.xml').write_text(xml)
    print(f'feed.xml: {len(items)} items, {len(xml) // 1024} KB')


def clean_stale(eps):
    live = {x['s'] for x in eps}
    epdir = SITE / 'ep'
    if epdir.exists():
        for d in epdir.iterdir():
            if d.is_dir() and d.name not in live:
                shutil.rmtree(d)
                print('removed stale', d.name)


def main():
    eps = build_data()
    for i, x in enumerate(eps):
        build_page(i, eps)
    print(f'ep pages: {len(list((SITE / "ep").glob("*/index.html")))}')
    build_sitemap(eps)
    build_disclaimer()
    build_llms(eps)
    build_feed(eps)
    clean_stale(eps)


if __name__ == '__main__':
    main()
