#!/usr/bin/env python3
"""多语言生成器：在 build.py 产物之上生成 /tw（繁体·台湾正体）与 /en（英文界面）两个静态镜像树。

用法：先跑 tools/build.py，再跑本脚本；gen_zh.py 的 deploy() 已挂到 rsync 之前。

/tw：OpenCC s2twp 全量转换（正文 + UI 字符串 + JSON-LD），站内链接改写到 /tw/ 前缀；
    app.js / ep.js / episodes.json / feed.xml / llms.txt 均出繁体副本。
/en：UI 字符串表替换 + 单集页外科手术（去掉中文精读面板、标题换英文原题、JSON-LD 重建），
    英文稿与音视频保持不变；不出英文 RSS（内容仍是中文精读）。
三棵树互相注入 hreflang 与语言切换器；sitemap 重写为三语 xhtml:link 交替链接。
本脚本幂等：build.py 重跑后重复执行结果一致（index.html 注入块先拆后装）。

依赖：pip3 install --user opencc-python-reimplemented
"""
import html as H
import json
import re
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
SITE = ROOT.parent / 'site'
DOMAIN = 'https://lex.qiaomu.ai'

try:
    from opencc import OpenCC
    cc = OpenCC('s2twp')
except ImportError:
    sys.exit('需要 opencc：pip3 install --user opencc-python-reimplemented')


def strip_no(t):
    return re.sub(r'^#\d+\s*[–—:-]?\s*', '', t or '').strip()


def conv(s):
    return cc.convert(s)


# ---------------------------------------------------------------- 数据
MASTER = json.load(open(ROOT / 'lex-master.json'))
TRANS = json.load(open(ROOT / 'translations.json')) if (ROOT / 'translations.json').exists() else {}
BY_SLUG = {e['slug']: e for e in MASTER}

PAGES = ['index.html', 'archive/index.html', 'disclaimer/index.html',
         '404.html', 'offline.html']
EP_HTML = sorted(str(p.relative_to(SITE)) for p in (SITE / 'ep').glob('*/index.html'))
EP_MD = sorted(str(p.relative_to(SITE)) for p in (SITE / 'ep').glob('*/index.md'))

SPECIAL_PATHS = {'404.html', 'offline.html'}   # 无 canonical，切换器指回各语言首页


def sub_path(rel):
    """页面相对路径 → 各语言 URL 路径；*/index.html 归一为目录形式（ep/x/、archive/）。"""
    if rel in SPECIAL_PATHS or rel == 'index.html':
        return '', 'tw/', 'en/'
    p = rel[:-len('index.html')] if rel.endswith('index.html') else rel
    return '', 'tw/' + p, 'en/' + p


def lang_switch(rel, active):
    z, t, e = sub_path(rel)
    on = ' aria-current="true"'
    return ('<!--i18n:lang--><nav class="lang-switch" aria-label="Language / 语言">'
            f'<a data-l="zh" href="/{z}" lang="zh-CN"{on if active == "zh" else ""}>简</a>'
            f'<a data-l="tw" href="/{t}" lang="zh-TW"{on if active == "tw" else ""}>繁</a>'
            f'<a data-l="en" href="/{e}" lang="en"{on if active == "en" else ""}>EN</a></nav><!--/i18n:lang-->')


def hreflang_block(rel):
    z, t, e = sub_path(rel)
    if rel in SPECIAL_PATHS:
        return ''
    return ('<!--i18n:alt-->'
            f'<link rel="alternate" hreflang="zh-CN" href="{DOMAIN}/{z}">'
            f'<link rel="alternate" hreflang="zh-TW" href="{DOMAIN}/{t}">'
            f'<link rel="alternate" hreflang="en" href="{DOMAIN}/{e}">'
            f'<link rel="alternate" hreflang="x-default" href="{DOMAIN}/{z}">'
            '<!--/i18n:alt-->')


def inject_base(html, rel, active='zh'):
    """基础树（简体）注入 hreflang + 切换器；幂等。"""
    html = re.sub(r'<!--i18n:lang-->.*?<!--/i18n:lang-->', '', html, flags=re.S)
    html = re.sub(r'<!--i18n:alt-->.*?<!--/i18n:alt-->', '', html, flags=re.S)
    sw = lang_switch(rel, active)
    if '<a class="mast-link"' in html:                      # 首页报头
        html = html.replace('<a class="mast-link"', sw + '<a class="mast-link"', 1)
    elif '<div class="header-actions">' in html:            # 内页 slim 报头
        html = html.replace('<div class="header-actions">',
                            '<div class="header-actions">' + sw, 1)
    alt = hreflang_block(rel)
    if alt:
        m = re.search(r'<link rel="canonical"[^>]*>', html)
        if m:
            html = html[:m.end()] + alt + html[m.end():]
    return html


# ---------------------------------------------------------------- /tw
LINK_PREFIX_RULES = [           # 站内页面链接加前缀；静态资源（/style.css /assets /og /transcripts 等）保持共享
    ('href="/ep/', 'href="/tw/ep/'),
    ('href="/archive/', 'href="/tw/archive/'),
    ('href="/disclaimer/', 'href="/tw/disclaimer/'),
    ('href="/feed.xml"', 'href="/tw/feed.xml"'),
    ('href="/llms.txt"', 'href="/tw/llms.txt"'),
    ('href="/#', 'href="/tw/#'),
    ('href="/?', 'href="/tw/?'),
    ('href="/"', 'href="/tw/"'),
]


def tw_patch(html, rel):
    html = conv(html)
    html = html.replace('<html lang="zh-CN">', '<html lang="zh-TW">', 1)
    html = html.replace('content="zh_CN"', 'content="zh_TW"')
    html = html.replace('"inLanguage": "zh-CN"', '"inLanguage": "zh-TW"')
    html = html.replace('<language>zh-CN</language>', '<language>zh-TW</language>')
    m = re.search(r'<link rel="canonical" href="' + re.escape(DOMAIN) + r'/([^"]*)">', html)
    if m:
        html = html[:m.start()] + f'<link rel="canonical" href="{DOMAIN}/tw/{m.group(1)}">' + html[m.end():]
    html = html.replace(f'property="og:url" content="{DOMAIN}/"',
                        f'property="og:url" content="{DOMAIN}/tw/"')
    html = html.replace(f'"url": "{DOMAIN}/"', f'"url": "{DOMAIN}/tw/"')
    for a, b in LINK_PREFIX_RULES:
        html = html.replace(a, b)
    # og:image、JSON-LD 里的 /og/ 分享图与 /#org 锚点不动；单集 URL 前缀统一改
    html = html.replace(f'{DOMAIN}/ep/', f'{DOMAIN}/tw/ep/')
    # 切换器：简体标签还原为「简」，active 移到繁体
    m = re.search(r'<!--i18n:lang-->.*?<!--/i18n:lang-->', html, flags=re.S)
    if m:
        seg = m.group(0).replace('簡', '简').replace('語言', '语言')
        seg = seg.replace('lang="zh-CN" aria-current="true"', 'lang="zh-CN"')
        seg = seg.replace('lang="zh-TW"', 'lang="zh-TW" aria-current="true"')
        html = html[:m.start()] + seg + html[m.end():]
    # 主题脚本里的复制 RSS 指向繁体 feed
    html = html.replace("location.origin + '/feed.xml'", "location.origin + '/tw/feed.xml'")
    html = html.replace('src="/app.js?v=', 'src="/tw/app.js?v=')
    html = html.replace('src="/ep.js?v=', 'src="/tw/ep.js?v=')
    return html


def tw_js(js):
    js = conv(js)
    js = js.replace("href=\"/ep/", "href=\"/tw/ep/")
    js = js.replace("'/ep/'", "'/tw/ep/'")
    js = js.replace('href="/archive/', 'href="/tw/archive/')
    js = js.replace("fetch('data/episodes.json')", "fetch('/tw/data/episodes.json')")
    return js


# ---------------------------------------------------------------- /en
def r_sub(html, pat, repl, count=0, flags=re.S):
    return re.sub(pat, lambda m, repl=repl: repl, html, count=count, flags=flags)


EN_SHARED = [   # 三棵页面共用的报头 / 页脚 / 弹层 / 无障碍文案（长串优先，避免误替换）
    ('<a class="skip-link" href="#main">跳到主要内容</a>', '<a class="skip-link" href="#main">Skip to content</a>'),
    ('aria-label="Lex Fridman 播客全访谈 · 首页"', 'aria-label="Lex Fridman Podcast Guide · Home"'),
    ('<span>播客全访谈</span>', '<span>Podcast Guide</span>'),
    ('← 全部单集', '← All episodes'),
    ('aria-label="搜索全部单集" title="搜索"', 'aria-label="Search all episodes" title="Search"'),
    ('aria-label="切换浅色 / 深色模式" title="切换浅色 / 深色模式"', 'aria-label="Toggle light / dark mode" title="Toggle light / dark mode"'),
    ('把世界上最好的长访谈，用中文认真读一遍。', 'The world’s best long-form interviews, read carefully in Chinese.'),
    ('<nav class="ft-col" aria-label="浏览"><h2>浏览</h2>', '<nav class="ft-col" aria-label="Browse"><h2>Browse</h2>'),
    ('<a href="/">全部单集</a><a href="/?f=zh">中文精读</a><a href="/archive/">单集目录</a><a href="/#search">搜索</a>',
     '<a href="/en/">All episodes</a><a href="/en/?f=zh">Deep reads</a><a href="/en/archive/">Episode index</a><a href="/en/#search">Search</a>'),
    ('安装为应用', 'Install app'),
    ('<nav class="ft-col" aria-label="订阅"><h2>订阅</h2>', '<nav class="ft-col" aria-label="Subscribe"><h2>Subscribe</h2>'),
    ('RSS 全文订阅', 'RSS feed · full text'),
    ('复制 RSS 地址', 'Copy RSS URL'),
    ('Lex Fridman Podcast 官方 RSS', 'Official Lex Fridman Podcast RSS'),
    ("sh.textContent = '链接已复制';", "sh.textContent = 'Link copied';"),
    ("cf.textContent = '已复制';", "cf.textContent = 'Copied';"),
    ('来自 lexfridman.com 官方播客 RSS', 'via the official lexfridman.com podcast RSS'),
    ('官方播客', 'Official podcast'),
    ('<nav class="ft-col" aria-label="关于"><h2>关于</h2>', '<nav class="ft-col" aria-label="About"><h2>About</h2>'),
    ('免责声明', 'Disclaimer'),
    ('开源代码', 'Open source'),
    ('作者 X', 'Author on X'),
    ('<h2>支持这个项目</h2>', '<h2>Support this project</h2>'),
    ('一个人独立制作，没有广告，也不收费。如果这里的某篇精读让你有所收获，欢迎请作者喝杯咖啡，让它一直做下去。',
     'Made independently by one person — no ads, no paywall. If a deep read here was worth your time, buy the author a coffee to keep it going.'),
    ('打赏支持', 'Donate'),
    ('关注公众号', 'Follow on WeChat'),
    ('© 2026 向阳乔木 · 非官方粉丝站点，与 Lex Fridman 及节目制作方无隶属关系',
     '© 2026 Qiaomu Xiangyang (向阳乔木) · Unofficial fan site, not affiliated with Lex Fridman or the show’s producers'),
    ('音视频与原始文稿版权归原权利方所有，本站不托管媒体文件 · 中文精读由 AI 改写，仅供学习参考',
     'Audio, video and original transcripts belong to their rights holders; this site hosts no media files · Deep reads are AI-rewritten, for study and reference only'),
    ('谢谢你的支持', 'Thank you for your support'),
    ('每一份打赏都会变成更多认真校过的精读', 'Every donation goes into more carefully checked deep reads'),
    ('alt="打赏二维码"', 'alt="Donation QR code"'),
    ('微信扫一扫', 'Scan with WeChat'),
    ('向下滑，选择「添加到主屏幕」', 'Scroll down and choose “Add to Home Screen”'),
    ('添加到主屏幕', 'Add to Home Screen'),
    ('像应用一样打开，读过的文章离线也能看', 'Opens like an app; pages you have read stay available offline'),
    ('点 Safari 底部的「分享」按钮', 'Tap the Share button in Safari'),
    ('点右上角「添加」', 'Tap “Add”'),
    ('关注向阳乔木', 'Follow Qiaomu Xiangyang'),
    ('微信公众号：向阳乔木推荐看', 'WeChat account: 向阳乔木推荐看'),
    ('alt="公众号二维码"', 'alt="WeChat QR code"'),
    ('aria-label="关闭"', 'aria-label="Close"'),
    ('Lex Fridman 播客全访谈 · 中文精读全文', 'Lex Fridman Podcast Guide · Chinese deep reads, full text'),
    ('Lex Fridman 播客全访谈', 'Lex Fridman Podcast Guide'),
    ('content="Lex 中文"', 'content="Lex Fridman Guide"'),
]

TR_NOTE_EN = {
    'ot': 'Transcript from the official release on lexfridman.com (with speakers and timestamps).',
    'kg': 'Transcript from the public Kaggle dataset (rajneesh231/lex-fridman-podcast-transcript), an early automatic transcription — it may contain recognition errors.',
    'asr': 'Transcript machine-generated on this site from the officially released audio; it may contain errors — for names and numbers, trust the audio.',
}

EN_EPI18N = [
    ('<span class="ap-label">官方音频</span>', '<span class="ap-label">Official audio</span>'),
    ('aria-label="播放 YouTube 视频"', 'aria-label="Play YouTube video"'),
    ('<span>看视频</span>', '<span>Watch video</span>'),
    ('aria-label="播放"', 'aria-label="Play"'),
    ('aria-label="播放进度"', 'aria-label="Playback position"'),
    ('aria-label="后退 15 秒"', 'aria-label="Back 15 seconds"'),
    ('aria-label="前进 15 秒"', 'aria-label="Forward 15 seconds"'),
    ('aria-label="播放速度"', 'aria-label="Playback speed"'),
    ('已从上次位置继续 · <button type="button" class="ap-restart">从头听</button>',
     'Resumed from where you left off · <button type="button" class="ap-restart">Start over</button>'),
    ('该期暂无音视频存档，可通过下方资源访问原始页面。', 'No archived audio or video for this episode — use the resources below to reach the original pages.'),
    ('该期文稿暂未收录。', 'No transcript archived for this episode yet.'),
    ('外部文稿：', 'External transcripts: '),
    ('aria-label="上一期 / 下一期"', 'aria-label="Previous / next episode"'),
    ('aria-label="精读目录"', 'aria-label="Table of contents"'),
    ('可直接收听上方音频或观看视频。', 'You can listen to the audio above or watch the video.'),
    ('<h2>本集资源与出处</h2>', '<h2>Resources &amp; sources</h2>'),
    ('<span class="res-k">视频</span>', '<span class="res-k">Video</span>'),
    ('<span class="res-k">音频</span>', '<span class="res-k">Audio</span>'),
    ('<span class="res-k">官网</span>', '<span class="res-k">Website</span>'),
    ('<span class="res-k">文稿</span>', '<span class="res-k">Transcript</span>'),
    ('在 YouTube 收看', 'Watch on YouTube'),
    ('官方 MP3 直链', 'Official MP3'),
    ('Lex Fridman 官网本集页面', 'Episode page on lexfridman.com'),    ('官方 Transcript（lexfridman.com）', 'Official transcript (lexfridman.com)'),
    ('HappyScribe 版文稿', 'HappyScribe transcript'),
    ('本站纯文本版', 'Plain text on this site'),
    ('官方文稿', 'Official transcript'),
    ('存档文稿', 'Archived transcript'),
    ('机器转写文稿', 'Machine transcript'),
]

EN_JS_APP = [
    ("'回到顶部'", "'Back to top'"),
    ('`${h} 小时 ${m} 分`', '`${h} hr ${m} min`'),
    ('`${m} 分钟`', '`${m} min`'),
    ('`第 ${e.n} 期`', '`Episode ${e.n}`'),
    ("'特别节目'", "'Special'"),
    ('<span class="zh-tag">中文精读</span>', '<span class="zh-tag">Deep read</span>'),
    ('href="/ep/${e.s}/"', 'href="/en/ep/${e.s}/"'),
    ("location.replace('/ep/'", "location.replace('/en/ep/'"),
    ("'<span class=\"end\">— 全部 ' + LIST.length + ' 期 —</span>'",
     "'<span class=\"end\">— All ' + LIST.length + ' episodes —</span>'"),
    ('再看 30 期', 'Show 30 more'),
    ('已显示 ${rendered} / ${LIST.length} 期 · <a href="/archive/">按年份浏览全部</a>',
     'Shown ${rendered} / ${LIST.length} · <a href="/en/archive/">Browse all by year</a>'),
    ("'加载中…'", "'Loading…'"),
    ("'搜索结果'", "'Search results'"),
    ("{ zh: '中文精读', tr: '有文稿', hist: '看过的' }", "{ zh: 'Deep reads', tr: 'With transcripts', hist: 'Read' }"),
    ('${LIST.length} 期${', '${LIST.length} episodes${'),
    ('与「${esc(state.q.trim())}」相关', 'matching “${esc(state.q.trim())}”'),
    ('>全部单集<', '>All episodes<'),
    ("'从第 1 期开始'", "'from episode 1'"),
    ("'最新在前'", "'latest first'"),
    ("['Elon Musk', 'AI', '物理', '历史', 'Sam Altman', '意识', '编程']",
     "['Elon Musk', 'AI', 'Physics', 'History', 'Sam Altman', 'Consciousness', 'Programming']"),
    ('没有找到${q ? `「${esc(q)}」` : \'符合条件的单集\'}', 'No results${q ? ` for “${esc(q)}”` : \'\'}'),
    ('试试嘉宾英文名、中文译名或话题关键词，多个词用空格分开。',
     'Try the guest’s English name or a topic keyword; separate multiple words with spaces.'),
    ('在全部单集中搜索', 'Search all episodes'),
    ("md.textContent = `${t.getFullYear()} 年 ${t.getMonth() + 1} 月 ${t.getDate()} 日 · 星期${'日一二三四五六'[t.getDay()]}`;",
     "md.textContent = t.toLocaleDateString('en-US', { weekday: 'long', year: 'numeric', month: 'long', day: 'numeric' });"),
    ('ms.textContent = `${DATA.length} 期深度访谈 · ${nZh} 篇中文精读${since ? ` · ${since.slice(0, 4)} 年至今` : \'\'}`;',
     'ms.textContent = `${DATA.length} episodes · ${nZh} deep reads${since ? ` · since ${since.slice(0, 4)}` : \'\'}`;'),
    ('最新精读', 'Latest deep read'),
    ('>阅读全文<', '>Read more<'),
    ('const d = e.d ? `${e.d.slice(0, 4)} 年 ${+e.d.slice(5, 7)} 月` : \'\';',
     'const d = e.d ? new Date(e.d + \'T00:00:00\').toLocaleDateString(\'en-US\', { month: \'short\', year: \'numeric\' }) : \'\';'),
    ('<p class="hero-en" lang="en">${esc(e._en)}</p>', ''),
    ("听到 ${fmtT(h.t)}${h.d ? ` · 剩 ${fmtT(h.d - h.t)}` : ''}", "Played ${fmtT(h.t)}${h.d ? ` · ${fmtT(h.d - h.t)} left` : ''}"),
    ('读到 ${Math.round((h.rp || 0) * 100)}%', 'Read ${Math.round((h.rp || 0) * 100)}%'),
    ("'最早' : '最新'", "'Earliest' : 'Latest'"),
    ("'当前：从第 1 期开始'", "'Now: from episode 1'"),
    ("'当前：最新一期在前'", "'Now: latest first'"),
    ("fetch('data/episodes.json')", "fetch('/en/data/episodes.json')"),
]

EN_JS_EP = [
    ("'回到顶部'", "'Back to top'"),
    ('在文稿中搜索…', 'Search in transcript…'),
    ('aria-label="在文稿中搜索"', 'aria-label="Search in transcript"'),
    ("'无匹配'", "'No matches'"),
    ('aria-label="上一处"', 'aria-label="Previous match"'),
    ('aria-label="下一处"', 'aria-label="Next match"'),
    ('点击时间戳可跳到音频对应位置', 'Click a timestamp to jump to that moment in the audio'),
    ('title="跳转到 ${t}"', 'title="Jump to ${t}"'),
    ('</svg>视频', '</svg>Video'),
    ("'暂停'", "'Pause'"),
    ("'播放'", "'Play'"),
    ('上次读到', 'Resumed at'),
    ('继续阅读', 'Resume reading'),
]

DISCLAIMER_EN = """<article class="ep">
      <header class="ep-head"><div class="ep-kicker">About this site</div><h1 class="ep-title">Disclaimer &amp; content notes</h1></header>
      <div class="zh-article disclaimer-body">
        <p>lex.qiaomu.ai is an unofficial reading guide for the Lex Fridman Podcast, built for readers who want to discover and understand the show. This site is not affiliated with Lex Fridman, the show’s producers, or any guest, and its content does not represent their views.</p>

        <h2>Copyright</h2>
        <p>All original content — audio, video, transcripts, titles and show names — belongs to Lex Fridman, the guests and the production team. This site hosts, stores and distributes no media files: audio streams from the official podcast RSS (blubrry); video and transcripts are linked to official pages or public sources. The site quotes original material only to the extent necessary, with attribution.</p>

        <h2>Chinese deep reads</h2>
        <p>The “deep reads” are AI-assisted Chinese retellings of the original interviews — derivative work, not official translations, and not reviewed by Lex Fridman or the guests. They may misread, omit or distort; treat the official audio and transcripts as authoritative wherever they differ.</p>

        <h2>Transcript sources</h2>
        <p>Episode transcripts fall into three categories, labelled in the transcript panel of each page:</p>
        <ul>
          <li>Official transcripts — published on lexfridman.com;</li>
          <li>Kaggle public dataset archive — early automatic transcription, may contain errors;</li>
          <li>Machine transcripts — generated on this site from the official audio; names and numbers should be trusted only against the audio.</li>
        </ul>

        <h2>Purpose</h2>
        <p>This is a non-commercial project with no ads and no fees, for study, search and discovery. If any rights holder finds any material here unsuitable, contact the site maintainer and it will be removed or corrected.</p>

        <h2>Contact</h2>
        <p>Corrections, suggestions and copyright matters: reach the maintainer via <a href="https://x.com/vista8" target="_blank" rel="noopener">X (@vista8)</a> or <a href="https://github.com/joeseesun/" target="_blank" rel="noopener">GitHub</a>.</p>
      </div>
    </article>"""


def en_common(html):
    for a, b in EN_SHARED:
        html = html.replace(a, b)
    return html


def en_switch_fix(html):
    """en 树里的切换器：active 移到 EN。"""
    m = re.search(r'<!--i18n:lang-->.*?<!--/i18n:lang-->', html, flags=re.S)
    if m:
        seg = m.group(0).replace('lang="zh-CN" aria-current="true"', 'lang="zh-CN"')
        seg = seg.replace('aria-label="Language / 语言"', 'aria-label="Language"')
        seg = seg.replace('lang="en"', 'lang="en" aria-current="true"')
        html = html[:m.start()] + seg + html[m.end():]
    return html


def en_alt_fix(html, rel):
    """en 树的 hreflang：把 zh-CN 与 x-default 指回简体版。"""
    z, t, e = sub_path(rel)
    html = re.sub(r'<!--i18n:alt-->.*?<!--/i18n:alt-->', '', html, flags=re.S)
    if rel in SPECIAL_PATHS:
        return html
    alt = ('<!--i18n:alt-->'
           f'<link rel="alternate" hreflang="zh-CN" href="{DOMAIN}/{z}">'
           f'<link rel="alternate" hreflang="zh-TW" href="{DOMAIN}/{t}">'
           f'<link rel="alternate" hreflang="en" href="{DOMAIN}/{e}">'
           f'<link rel="alternate" hreflang="x-default" href="{DOMAIN}/{z}">'
           '<!--/i18n:alt-->')
    m = re.search(r'<link rel="canonical"[^>]*>', html)
    if m:
        html = html[:m.end()] + alt + html[m.end():]
    return html


def en_head(html, title, desc, canonical_path):
    html = r_sub(html, r'<title>.*?</title>', f'<title>{H.escape(title)}</title>', 1)
    html = r_sub(html, r'<meta name="description" content="[^"]*">',
                 f'<meta name="description" content="{H.escape(desc)}">', 1)
    html = r_sub(html, r'<meta property="og:title" content="[^"]*">',
                 f'<meta property="og:title" content="{H.escape(title)}">', 1)
    html = r_sub(html, r'<meta property="og:description" content="[^"]*">',
                 f'<meta property="og:description" content="{H.escape(desc)}">', 1)
    html = r_sub(html, r'<meta property="og:url" content="[^"]*">',
                 f'<meta property="og:url" content="{DOMAIN}/{canonical_path}">', 1)
    html = r_sub(html, r'<meta name="twitter:title" content="[^"]*">',
                 f'<meta name="twitter:title" content="{H.escape(title)}">', 1)
    html = r_sub(html, r'<meta name="twitter:description" content="[^"]*">',
                 f'<meta name="twitter:description" content="{H.escape(desc)}">', 1)
    html = re.sub(r'<link rel="canonical" href="[^"]*">',
                  f'<link rel="canonical" href="{DOMAIN}/{canonical_path}">', html, count=1)
    return html


def en_index(html):
    n = len(MASTER)
    n_zh = len(json.load(open(SITE / 'data' / 'zh-index.json')).get('slugs', []))
    since = min((e.get('date') or '9999') for e in MASTER)[:4]
    html = html.replace('<html lang="zh-CN">', '<html lang="en">', 1)
    html = html.replace('<meta property="og:locale" content="zh_CN">',
                        '<meta property="og:locale" content="en_US">')
    html = en_common(html)
    html = en_head(html,
                   f'Lex Fridman Podcast Guide · {n} episodes · audio, video, transcripts & Chinese deep reads',
                   f'Unofficial guide to all {n} episodes of the Lex Fridman Podcast: official audio, YouTube video, English transcripts, and AI-written Chinese deep reads.',
                   'en/')
    html = re.sub(r'href="' + re.escape(DOMAIN) + r'/"', f'href="{DOMAIN}/en/"', html)
    # 报头副标题（SSR）
    html = re.sub(r'\d+ 期深度访谈 · \d+ 篇中文精读 · \d{4} 年至今',
                  f'{n} episodes · {n_zh} deep reads · since {since}', html)
    html = html.replace('>RSS 订阅<', '>RSS<')
    html = html.replace('placeholder="搜索嘉宾、话题、期数…"', 'placeholder="Search guests, topics, episode #…"')
    html = html.replace('aria-label="搜索单集"', 'aria-label="Search episodes"')
    html = html.replace('>清除</button>', '>Clear</button>')
    html = html.replace('aria-label="清除搜索"', 'aria-label="Clear search"')
    html = html.replace('aria-label="筛选"', 'aria-label="Filters"')
    html = html.replace('>全部</button>', '>All</button>')
    html = html.replace('>中文精读<span class="n"', '>Deep reads<span class="n"')
    html = html.replace('>有文稿<span class="n"', '>With transcripts<span class="n"')
    html = html.replace('>看过<span class="n"', '>Read<span class="n"')
    html = html.replace('aria-label="切换排序"', 'aria-label="Toggle sort order"')
    html = html.replace('<span>最新</span>', '<span>Latest</span>')
    html = html.replace('aria-label="最新精读"', 'aria-label="Latest deep read"')
    html = html.replace('<h2 id="cont-h">继续</h2>', '<h2 id="cont-h">Continue</h2>')
    html = html.replace('清除记录', 'Clear')
    html = html.replace('<div class="hero-kicker">最新精读</div>', '<div class="hero-kicker">Latest deep read</div>')
    html = html.replace('>阅读全文<', '>Read more<')
    # 头条：标题直接换成已有的英文副题，副题行与中文简介删除
    html = re.sub(r'<h2 class="hero-title"><a href="/ep/([a-z0-9-]+)/">.*?</a></h2><p class="hero-en" lang="en">(.*?)</p>',
                  lambda m: f'<h2 class="hero-title"><a href="/ep/{m.group(1)}/">{m.group(2)}</a></h2>',
                  html, count=1, flags=re.S)
    html = re.sub(r'<p class="hero-desc">.*?</p>', '', html, count=1, flags=re.S)
    # 头条署名：日期 · 期数（英文）
    mh = re.search(r'data-s="([a-z0-9-]+)"', html)
    if mh and mh.group(1) in BY_SLUG:
        e = BY_SLUG[mh.group(1)]
        bits = []
        if e.get('date'):
            import datetime
            try:
                bits.append(datetime.date.fromisoformat(e['date']).strftime('%b %Y'))
            except ValueError:
                pass
        if e.get('num') is not None:
            bits.append(f'Episode {e["num"]}')
        if bits:
            html = re.sub(r'<p class="hero-by">.*?</p>',
                          f'<p class="hero-by">{" · ".join(bits)}</p>', html, count=1, flags=re.S)
    # 卡片：标题用已有的英文副题替换中文标题（无英文副题的卡片标题本就是英文原题）
    html = re.sub(r'<div class="card-title">.*?</div><div class="card-title-en" lang="en">(.*?)</div>',
                  lambda m: f'<div class="card-title">{m.group(1)}</div>', html)
    html = html.replace('<span class="zh-tag">中文精读</span>', '<span class="zh-tag">Deep read</span>')
    html = re.sub(r'<span class="ep-n">第 (\d+) 期</span>', r'<span class="ep-n">Episode \1</span>', html)
    html = html.replace('<span class="ep-n">特别节目</span>', '<span class="ep-n">Special</span>')
    # JSON-LD 重建
    m = re.search(r'<script type="application/ld\+json">(.*?)</script>', html, re.S)
    if m:
        try:
            ld = json.loads(m.group(1))
            g = ld.get('@graph', [])
            for node in g:
                if node.get('@type') == 'WebSite':
                    node['description'] = (f'Unofficial guide to all {n} episodes of the Lex Fridman Podcast: '
                                           f'official audio, video, English transcripts and {n_zh} AI-written Chinese deep reads.')
                elif node.get('@type') == 'Organization':
                    node['founder']['name'] = 'Qiaomu Xiangyang (向阳乔木)'
                elif node.get('@type') == 'ItemList':
                    node['name'] = 'Latest episodes'
                    for item in node.get('itemListElement', []):
                        slug = (item.get('url') or '').rstrip('/').rsplit('/', 1)[-1]
                        if slug in BY_SLUG:
                            item['name'] = strip_no(BY_SLUG[slug]['title'])
            txt = json.dumps(ld, ensure_ascii=False).replace('<', '\\u003c')
            html = html[:m.start()] + '<script type="application/ld+json">' + txt + '</script>' + html[m.end():]
        except Exception as ex:
            print('en index JSON-LD rebuild failed:', ex)
    html = html.replace('src="/app.js?v=', 'src="/en/app.js?v=')
    return en_switch_fix(en_alt_fix(html, 'index.html'))


def en_ep(html, rel):
    slug = rel.split('/')[1]
    e = BY_SLUG.get(slug, {})
    num, title = e.get('num'), e.get('title', slug)
    orig = strip_no(title)
    has_zh = 'id="panel-zh"' in html
    ep_desc = (f'{orig} — ' + (f'Episode #{num} of the Lex Fridman Podcast' if num is not None
                               else 'A Lex Fridman Podcast episode')
               + '. Official audio, video and the full transcript.')
    title_tag = f'{orig} | Lex Fridman Podcast' + (f' #{num}' if num is not None else '')

    html = html.replace('<html lang="zh-CN">', '<html lang="en">', 1)
    html = html.replace('<meta property="og:locale" content="zh_CN">',
                        '<meta property="og:locale" content="en_US">')
    html = html.replace(f'<link rel="canonical" href="{DOMAIN}/ep/{slug}/">',
                        f'<link rel="canonical" href="{DOMAIN}/en/ep/{slug}/">')
    html = html.replace(f'property="og:url" content="{DOMAIN}/ep/{slug}/"',
                        f'property="og:url" content="{DOMAIN}/en/ep/{slug}/"')
    html = en_common(html)
    html = en_head(html, title_tag, ep_desc, f'en/ep/{slug}/')
    html = html.replace('title="中文精读 Markdown"', 'title="Chinese deep read · Markdown"')
    # 分享图 alt：中文标题｜英文标题 → 英文
    html = r_sub(html, r'<meta property="og:image:alt" content="[^"]*">',
                 f'<meta property="og:image:alt" content="{H.escape(orig)}">')
    html = r_sub(html, r'<meta name="twitter:image:alt" content="[^"]*">',
                 f'<meta name="twitter:image:alt" content="{H.escape(orig)}">')

    # 头部：h1 换英文原题；副题、中文简介删除
    m = re.search(r'<p class="ep-title-en" lang="en">(.*?)</p>', html, re.S)
    if m:
        html = re.sub(r'<h1 class="ep-title">.*?</h1>', f'<h1 class="ep-title">{m.group(1)}</h1>', html, count=1, flags=re.S)
        html = html.replace(m.group(0), '')
    html = re.sub(r'\s*<p class="ep-dek">.*?</p>', '', html, count=1, flags=re.S)

    # kicker：Episode N / Special · Deep read 徽标
    def kicker(m):
        inner = m.group(1)
        inner = re.sub(r'第 (\d+) 期', r'Episode \1', inner)
        inner = inner.replace('特别节目', 'Special episode')
        inner = inner.replace('<span class="k-zh">中文精读</span>', '<span class="k-zh">Deep read</span>')
        return f'<div class="ep-kicker">{inner}</div>'
    html = re.sub(r'<div class="ep-kicker">(.*?)</div>', kicker, html, count=1, flags=re.S)

    # byline：保留日期与文稿来源，去掉中文嘉宾名与精读字数
    mb = re.search(r'<div class="ep-byline">(.*?)</div>', html, re.S)
    if mb:
        seg = mb.group(1)
        dt = re.search(r'<time datetime="(\d{4}-\d{2}-\d{2})">.*?</time>', seg)
        src = next((en for zh, en in [('官方文稿', 'Official transcript'), ('存档文稿', 'Archived transcript'),
                                      ('机器转写文稿', 'Machine transcript')] if zh in seg), None)
        import datetime as _dt
        bits = []
        if dt:
            try:
                bits.append(_dt.date.fromisoformat(dt.group(1)).strftime('%b %Y'))
            except ValueError:
                pass
        if src:
            bits.append(f'<span>{src}</span>')
        sep = '<span class="k-sep">·</span>'
        new = f'<div class="ep-byline">{sep.join(bits)}</div>' if bits else ''
        html = html.replace(mb.group(0), new)
        if has_zh:
            html = html.replace(new, new + (f'<p class="ep-also">This episode also has a '
                                            f'<a href="{DOMAIN}/ep/{slug}/" lang="zh-CN" hreflang="zh-CN">Chinese deep read（中文精读）</a>.</p>'))

    # tab：去掉中文精读按钮与面板（面板内含 colophon，一并移除）
    html = re.sub(r'<button class="tab-btn" type="button" data-tab="zh"[^>]*>.*?</button>', '', html, flags=re.S)
    html = re.sub(r'<div class="tab-panel" id="panel-zh".*?(?=<div class="tab-panel" id="panel-tr"|<div class="ep-notice">|<section class="ep-resources")',
                  '', html, flags=re.S)
    html = html.replace('>英文文稿</button>', '>Transcript</button>')

    # 文稿来源说明（三种原文精确替换）
    for zh, en in [
        ('文稿来自 Lex Fridman 官网公开发布的官方 Transcript（含说话人与时间戳）。', TR_NOTE_EN['ot']),
        ('文稿来自公开 Kaggle 数据集（rajneesh231/lex-fridman-podcast-transcript），为早期自动转录存档，可能存在识别错误。', TR_NOTE_EN['kg']),
        ('文稿由本站用语音识别模型（基于官方发布音频）机器转写，可能有识别错误，人名与数字请以音频为准。', TR_NOTE_EN['asr']),
    ]:
        html = html.replace(zh, en)

    # 上一期 / 下一期：用英文原题重建
    def pn(m):
        s, relattr = m.group(1), m.group(2)
        pe = BY_SLUG.get(s, {})
        label = '← Previous' if relattr == 'prev' else 'Next →'
        t = strip_no(pe.get('title', s))
        if pe.get('num') is not None:
            t = f'#{pe["num"]} {t}'
        return (f'<a href="/en/ep/{s}/" rel="{relattr}">'
                f'<span class="pn-k">{label}</span><span class="pn-t">{H.escape(t)}</span></a>')
    html = re.sub(r'<a href="/ep/([a-z0-9-]+)/" rel="(prev|next)"><span class="pn-k">.*?</span><span class="pn-t">.*?</span></a>',
                  pn, html, flags=re.S)

    # 音视频 / 资源区
    for a, b in EN_EPI18N:
        html = html.replace(a, b)
    # 播放器标题：换英文原题
    if orig:
        html = re.sub(r'data-title="[^"]*"', f'data-title="{H.escape(orig)}"', html, count=1)

    # JSON-LD：删 Article 节点，Episode 换英文描述
    m = re.search(r'<script type="application/ld\+json">(.*?)</script>', html, re.S)
    if m:
        try:
            ld = json.loads(m.group(1))
            g = [n for n in ld.get('@graph', []) if n.get('@type') != 'Article']
            for node in g:
                if node.get('@type') == 'PodcastEpisode':
                    node['description'] = ep_desc
                    node['name'] = orig
                    node.pop('alternativeHeadline', None)
                elif node.get('@type') == 'Organization' and 'founder' in node:
                    node['founder']['name'] = 'Qiaomu Xiangyang (向阳乔木)'
                elif node.get('@type') == 'BreadcrumbList':
                    for item in node.get('itemListElement', []):
                        if item.get('position') == 1:
                            item['name'] = 'Home'
                        elif item.get('position') == 2:
                            item['name'] = title_tag.split(' | ')[0]
            ld['@graph'] = g
            txt = json.dumps(ld, ensure_ascii=False).replace('<', '\\u003c')
            html = html[:m.start()] + '<script type="application/ld+json">' + txt + '</script>' + html[m.end():]
        except Exception as ex:
            print(f'en ep {slug} JSON-LD rebuild failed:', ex)

    html = html.replace('src="/ep.js?v=', 'src="/en/ep.js?v=')
    return en_switch_fix(en_alt_fix(html, rel))


def en_archive(html):
    n = len(MASTER)
    html = html.replace('<html lang="zh-CN">', '<html lang="en">', 1)
    html = html.replace('<meta property="og:locale" content="zh_CN">',
                        '<meta property="og:locale" content="en_US">')
    html = en_common(html)
    desc = (f'Every episode of the Lex Fridman Podcast ({n} in total), grouped by year, '
            'with links to audio, video, English transcripts and Chinese deep reads.')
    html = en_head(html, f'Episode index · all {n} episodes · Lex Fridman Podcast Guide', desc, 'en/archive/')
    html = re.sub(r'href="' + re.escape(DOMAIN) + r'/archive/"', f'href="{DOMAIN}/en/archive/"', html)
    html = html.replace('<div class="ep-kicker">单集目录</div>', '<div class="ep-kicker">Episode index</div>')
    html = html.replace('aria-label="按年份跳转"', 'aria-label="Jump to year"')
    html = re.sub(r'全部 (\d+) 期', r'All \1 episodes', html)
    html = html.replace('从 2018 年的第一期到最新一期，按年份排列；标有「精读」的单集附中文长文。',
                        'From the first episode in 2018 to the latest, grouped by year; episodes marked “Deep read” include a Chinese long-form article.')
    html = re.sub(r'含 \d+ 篇中文精读、官方音频、视频与英文文稿。',
                  'with Chinese deep reads, official audio, video and English transcripts.', html)
    # CollectionPage JSON-LD 重建（name/description 原为中文）
    m = re.search(r'<script type="application/ld\+json">(.*?)</script>', html, re.S)
    if m:
        try:
            ld = json.loads(m.group(1))
            if ld.get('@type') == 'CollectionPage':
                ld['name'] = f'Episode index · all {n} episodes · Lex Fridman Podcast Guide'
                ld['description'] = desc
                ld['inLanguage'] = 'en'
                txt = json.dumps(ld, ensure_ascii=False).replace('<', '\\u003c')
                html = html[:m.start()] + '<script type="application/ld+json">' + txt + '</script>' + html[m.end():]
        except Exception as ex:
            print('en archive JSON-LD rebuild failed:', ex)
    # 目录行：标题换英文原题（保留期号与日期列）
    def row(m):
        s = m.group(1)
        e = BY_SLUG.get(s, {})
        t = H.escape(strip_no(e.get('title', s)))
        return re.sub(r'<span class="ar-t"><b>.*?</b>(<i lang="en">.*?</i>)?</span>',
                      f'<span class="ar-t"><b>{t}</b></span>', m.group(0), flags=re.S)
    html = re.sub(r'<li><a href="/ep/([a-z0-9-]+)/">.*?</a></li>', row, html, flags=re.S)
    html = html.replace('<span class="ar-zh">精读</span>', '<span class="ar-zh">Deep read</span>')
    html = re.sub(r'<small>(\d+) 期</small>', r'<small>\1</small>', html)
    html = html.replace('年份未知', 'Unknown year')
    html = html.replace('<script src="/app.js', '<script src="/en/app.js')
    return en_switch_fix(en_alt_fix(html, 'archive/index.html'))


def en_disclaimer(html):
    html = html.replace('<html lang="zh-CN">', '<html lang="en">', 1)
    html = en_common(html)
    html = en_head(html, 'Disclaimer & content notes · Lex Fridman Podcast Guide',
                   'Site nature, copyright, deep-read and transcript sources, feedback and takedown process.',
                   'en/disclaimer/')
    html = re.sub(r'href="' + re.escape(DOMAIN) + r'/disclaimer/"', f'href="{DOMAIN}/en/disclaimer/"', html)
    html = re.sub(r'<article class="ep">.*</article>', DISCLAIMER_EN, html, count=1, flags=re.S)
    html = re.sub(r'<a href="/">← 返回全部单集</a>', '<a href="/en/">← All episodes</a>', html)
    html = html.replace('<script src="/app.js', '<script src="/en/app.js')
    return en_switch_fix(en_alt_fix(html, 'disclaimer/index.html'))


def en_special(html, rel):
    html = html.replace('<html lang="zh-CN">', '<html lang="en">', 1)
    html = en_common(html)
    if rel == '404.html':
        html = html.replace('<div class="ep-kicker">页面不存在</div>', '<div class="ep-kicker">Page not found</div>')
        html = html.replace('<h1 class="ep-title">这一页没有找到</h1>', '<h1 class="ep-title">We couldn’t find that page</h1>')
        html = html.replace('链接可能写错了，或者那一期换了地址。试试搜索，或者从最新的几篇精读读起。',
                            'The link may be wrong, or the episode may have moved. Try a search, or start from the latest deep reads.')
        html = html.replace('<h2>最新精读</h2>', '<h2>Latest deep reads</h2>')
        html = re.sub(r'<i>第 (\d+) 期</i>', r'<i>Episode \1</i>', html)
        html = re.sub(r'<a class="more-btn" href="/">回到首页</a>', '<a class="more-btn" href="/en/">Home</a>', html)
        html = re.sub(r'<a class="more-btn ghost" href="/#search">搜索单集</a>', '<a class="more-btn ghost" href="/en/#search">Search</a>', html)
    else:
        html = html.replace('<div class="ep-kicker">离线</div>', '<div class="ep-kicker">Offline</div>')
        html = html.replace('<h1 class="ep-title">现在没有网络</h1>', '<h1 class="ep-title">You’re offline</h1>')
        html = html.replace('读过的文章已为你离线保存，可以返回上一页继续阅读；联网后会自动恢复。',
                            'Pages you have read are saved for offline reading. Go back to continue; everything refreshes once you reconnect.')
    # 卡片标题 / 推荐列表里的中文标题换英文
    html = re.sub(r'(<a href="/ep/([a-z0-9-]+)/">)<b>.*?</b>',
                  lambda m: m.group(1) + (f'<b>{H.escape(strip_no(BY_SLUG[m.group(2)]["title"]))}</b>'
                                          if m.group(2) in BY_SLUG else m.group(0)[len(m.group(1)):]), html, flags=re.S)
    html = html.replace('<script src="/app.js', '<script src="/en/app.js')
    return en_switch_fix(html)


# ---------------------------------------------------------------- sitemap / 数据 / js 副本
def rebuild_sitemap():
    src = (SITE / 'sitemap.xml').read_text()
    # 幂等：无论源是 build.py 的纯 <url> 还是本函数上次输出的带 xhtml:link 版本，都逐块取字段
    pairs = []
    for blk in re.findall(r'<url>(.*?)</url>', src, re.S):
        loc = re.search(r'<loc>(.*?)</loc>', blk)
        lm = re.search(r'<lastmod>(.*?)</lastmod>', blk)
        pri = re.search(r'<priority>(.*?)</priority>', blk)
        if loc and lm and pri:
            pairs.append((loc.group(1), lm.group(1), pri.group(1)))
    out = ['<?xml version="1.0" encoding="UTF-8"?>',
           '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9" '
           'xmlns:xhtml="http://www.w3.org/1999/xhtml">']
    seen = set()
    for loc, lm, pri in pairs:
        path = loc[len(DOMAIN):]
        if path in seen:
            continue
        seen.add(path)
        rel = path.lstrip('/')
        if rel.startswith('ep/'):
            z, t, e = rel, f'tw/{rel}', f'en/{rel}'
        elif rel in ('', 'archive/', 'disclaimer/'):
            z = rel
            t = f'tw/{rel}' if rel else 'tw/'
            e = f'en/{rel}' if rel else 'en/'
        else:
            continue
        entries = [(f'{DOMAIN}/{z}', 'zh-CN'), (f'{DOMAIN}/{t}', 'zh-TW'), (f'{DOMAIN}/{e}', 'en')]
        links = ''.join(f'<xhtml:link rel="alternate" hreflang="{l}" href="{u}"/>' for u, l in entries)
        out.append(f'<url><loc>{DOMAIN}/{z}</loc><lastmod>{lm}</lastmod><priority>{pri}</priority>'
                   f'<xhtml:link rel="alternate" hreflang="x-default" href="{DOMAIN}/{z}"/>{links}</url>')
    out.append('</urlset>')
    (SITE / 'sitemap.xml').write_text('\n'.join(out))
    print(f'sitemap.xml: {len(out) - 2} urls × 3 langs (hreflang)')


def build_episodes_json():
    data = json.load(open(SITE / 'data' / 'episodes.json'))
    tw = json.loads(json.dumps(data, ensure_ascii=False))
    for e in tw['episodes']:
        for k in ('zh', 'guest', 'ds'):
            if e.get(k):
                e[k] = conv(e[k])
    d = SITE / 'tw' / 'data'
    d.mkdir(parents=True, exist_ok=True)
    (d / 'episodes.json').write_text(json.dumps(tw, ensure_ascii=False, separators=(',', ':')))
    en = json.loads(json.dumps(data, ensure_ascii=False))
    for e in en['episodes']:
        for k in ('zh', 'guest', 'ds'):
            e.pop(k, None)
    d = SITE / 'en' / 'data'
    d.mkdir(parents=True, exist_ok=True)
    (d / 'episodes.json').write_text(json.dumps(en, ensure_ascii=False, separators=(',', ':')))
    print('episodes.json ×2 (tw converted / en English-only): ok')


def build_js_copies():
    (SITE / 'tw').mkdir(exist_ok=True)
    (SITE / 'en').mkdir(exist_ok=True)
    (SITE / 'tw' / 'app.js').write_text(tw_js((SITE / 'app.js').read_text()))
    (SITE / 'tw' / 'ep.js').write_text(tw_js((SITE / 'ep.js').read_text()))
    en_app = SITE / 'en' / 'app.js'
    src = (SITE / 'app.js').read_text()
    for a, b in EN_JS_APP:
        if a not in src:
            print(f'  ! en app.js 未命中: {a[:60]}...')
        src = src.replace(a, b)
    en_app.write_text(src)
    src = (SITE / 'ep.js').read_text()
    for a, b in EN_JS_EP:
        if a not in src:
            print(f'  ! en ep.js 未命中: {a[:60]}...')
        src = src.replace(a, b)
    (SITE / 'en' / 'ep.js').write_text(src)
    print('app.js / ep.js copies: ok')


def build_feeds_llms():
    # /tw/feed.xml：全文转换 + 链接前缀
    feed = (SITE / 'feed.xml').read_text()
    feed = conv(feed)
    feed = feed.replace(f'<link>{DOMAIN}/</link>', f'<link>{DOMAIN}/tw/</link>')
    feed = feed.replace(f'<atom:link href="{DOMAIN}/feed.xml"', f'<atom:link href="{DOMAIN}/tw/feed.xml"')
    feed = feed.replace(f'{DOMAIN}/ep/', f'{DOMAIN}/tw/ep/')
    feed = feed.replace('<language>zh-CN</language>', '<language>zh-TW</language>')
    (SITE / 'tw' / 'feed.xml').write_text(feed)
    # /tw/llms.txt
    llms = (SITE / 'llms.txt').read_text()
    llms = conv(llms).replace(f'{DOMAIN}/ep/', f'{DOMAIN}/tw/ep/').replace(f'{DOMAIN}/archive/', f'{DOMAIN}/tw/archive/')
    llms = llms.replace(f'> {DOMAIN}/tw/ep/', f'> {DOMAIN}/tw/ep/')
    (SITE / 'tw' / 'llms.txt').write_text(llms)
    # /en/llms.txt：英文标题重建
    n = len(MASTER)
    lines = [f'# Lex Fridman Podcast Guide (lex.qiaomu.ai/en)', '',
             f'> Unofficial guide to all {n} episodes of the Lex Fridman Podcast: official audio links, YouTube video, '
             f'full English transcripts, and AI-written Chinese deep reads (site UI in English, content links marked).', '',
             '## Usage', '',
             f'- Episode pages: {DOMAIN}/en/ep/{{slug}}/ (audio, video, transcript)',
             f'- Chinese deep reads (zh-CN, Markdown at /ep/{{slug}}/index.md): linked from each episode page',
             f'- All-episode index by year: {DOMAIN}/en/archive/', '',
             '## Episodes', '']
    for e in MASTER:
        num = e.get('num')
        t = strip_no(e['title'])
        head = f'#{num} {t}' if num is not None else t
        d = TRANS.get(e['slug'], {}) or {}
        guest = d.get('guest', '')
        lines.append(f'- [{head}]({DOMAIN}/en/ep/{e["slug"]}/)')
    (SITE / 'en' / 'llms.txt').write_text('\n'.join(lines) + '\n')
    print('feed.xml (tw) / llms.txt (tw+en): ok')


# ---------------------------------------------------------------- main
def main():
    # 1) 基础树注入 hreflang + 切换器（幂等）
    for rel in PAGES + EP_HTML:
        f = SITE / rel
        f.write_text(inject_base(f.read_text(), rel))
    # 2) /tw 树
    if (SITE / 'tw').exists():
        shutil.rmtree(SITE / 'tw')
    n = 0
    for rel in PAGES + EP_HTML + EP_MD:
        src = SITE / rel
        if not src.exists():
            continue
        dst = SITE / 'tw' / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        dst.write_text(tw_patch(src.read_text(), rel))
        n += 1
    print(f'/tw: {n} pages converted (s2twp)')
    # 3) /en 树
    if (SITE / 'en').exists():
        shutil.rmtree(SITE / 'en')
    for rel in ['index.html']:
        dst = SITE / 'en' / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        dst.write_text(en_index((SITE / rel).read_text()))
    n = 1
    for rel in EP_HTML:
        dst = SITE / 'en' / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        dst.write_text(en_ep((SITE / rel).read_text(), rel))
        n += 1
    for rel, fn in [('archive/index.html', en_archive), ('disclaimer/index.html', en_disclaimer),
                    ('404.html', en_special), ('offline.html', en_special)]:
        src = SITE / rel
        if not src.exists():
            continue
        dst = SITE / 'en' / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        dst.write_text(fn(src.read_text(), rel) if fn is en_special else fn(src.read_text()))
        n += 1
    print(f'/en: {n} pages built (UI in English)')
    # 4) 数据与脚本副本 / feed / llms / sitemap
    build_episodes_json()
    build_js_copies()
    build_feeds_llms()
    rebuild_sitemap()
    # 5) 质检：/en 残留中文统计（切换器里的 简/繁 是有意保留，先剔除）
    cjk = re.compile(r'[\u4e00-\u9fff]')
    leftovers = {}
    for rel in ['index.html', 'archive/index.html', 'disclaimer/index.html'] + EP_HTML:
        txt = (SITE / 'en' / rel).read_text()
        txt = re.sub(r'<!--i18n:lang-->.*?<!--/i18n:lang-->', '', txt, flags=re.S)
        txt = re.sub(r'//.*', '', txt)   # 内联 JS 注释不面向读者，不计入
        hits = set(cjk.findall(txt))
        if hits:
            leftovers[rel] = ''.join(sorted(hits))[:60]
    print(f'/en CJK check: {len(leftovers)} pages contain Chinese (switcher excluded; '
          'expected whitelist: also-zh link, WeChat/author names)')
    for rel, s in list(leftovers.items())[:8]:
        print(f'    {rel}: {s}')


if __name__ == '__main__':
    main()
