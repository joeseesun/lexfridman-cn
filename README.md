# lexfridman-cn

[Lex Fridman Podcast](https://lexfridman.com/) 全部 506 期的中文导航站生成器 —— [lex.qiaomu.ai](https://lex.qiaomu.ai/)。

纯静态多页站：每期一个独立 URL,含官方音频播放器(断点续听/倍速/时间戳跳转)、点击加载的 YouTube 封面、中英双语标题、英文文稿、AI 中文精读,以及全站 JSON-LD / sitemap / llms.txt / RSS 全文订阅。

> 本仓库只包含**代码与元数据**。受版权保护的内容(官方文稿、存档文稿、ASR 文稿、中文精读全文)不入库,由数据管线在本地自行获取/生成,详见下文。

## 架构

```
官方 RSS (lexfridman.com/feed/)
        │  tools/sync_new.py        每日对账:新期 → master/feed_audio → 标题翻译
        │                            文稿三梯队:官方 > ASR(本地 whisper) > 存档
        ▼
tools/lex-master.json     506 期元数据(期号/标题/日期/slug/YouTube ID)
tools/translations.json   AI 中文标题 / 嘉宾 / 一句话简介
tools/official/*.txt      官方文稿(fetch_official.py 抓取)
site/transcripts/*.txt    存档/ASR 文稿(不入库)
        │  tools/gen_zh.py --watch   中文精读批产(校验禁句式、带反馈重试)
        ▼
site/zh/*.html            中文精读片段(不入库)
        │  tools/build.py           全量构建:506 个单集页 + sitemap + llms.txt + RSS
        ▼
site/  ──rsync──►  Nginx 静态主机
```

- **sync_new.py** — 与官方 RSS 对账:新期自动补 master(含抓单集页取 YouTube ID)、回填官方文稿链接、跑标题翻译、无文稿的新期下载官方 MP3 用本地 whisper 转写,并保证精读管线存活,最后 build + rsync。
- **gen_zh.py --watch** — 精读批产:系统提示词驱动的长文改写,内置禁句式校验(机器翻译腔)、不合格带反馈重试、每 10 分钟扫新文稿、每 30 篇自动部署。模型走 [Magpie](https://magpie.qiaomu.ai) 网关的多路由轮换(按质量动态排序)。
- **build.py** — 全量静态构建:单集页(音频播放器/视频封面/tabs/JSON-LD/上下期)、首页、sitemap、llms.txt、RSS(最新 20 期,精读全文输出)。

## 快速开始

```bash
git clone https://github.com/joeseesun/lexfridman-cn.git
cd lexfridman-cn

# 数据文件(lex-master.json / translations.json / feed_audio.json)已在 tools/ 内
python3 tools/build.py          # 生成 site/,无文稿数据也能构建出骨架站
python3 -m http.server 8123 -d site
```

精读与同步管线(可选,需要 macOS + 额外依赖):

```bash
# Magpie API key 放在 macOS keychain: security add-generic-password -s qiaomu-llm -a magpie -w <KEY>
python3 tools/sync_new.py            # 同步新一期(RSS 对账 → 文稿 → 精读管线)
python3 tools/gen_zh.py --watch      # 精读批产
pip install mlx-whisper              # 本地 ASR(Apple Silicon)
```

## 版权与免责

- 代码以 [MIT](LICENSE) 授权。
- Lex Fridman Podcast 的音频、视频、文稿版权归 Lex Fridman 及相应嘉宾与制作方所有;本仓库不包含、不分发任何媒体文件与文稿内容。
- 中文精读为 AI 辅助生成的二次创作,非官方翻译。站点全文见 [lex.qiaomu.ai/disclaimer/](https://lex.qiaomu.ai/disclaimer/)。

## 更新节奏

上游每发布一期,`sync_new.py` 每日定时同步一次;文稿到位后精读批产自动跟进,无需人工介入。solo 特别节目等 RSS 非标准条目需手工补 master。
