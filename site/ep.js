/* Lex Fridman 播客 · 单集页：tab 切换 / 阅读设置 / 目录 / 视频懒加载 / 官方音频播放器 */
(function () {
  'use strict';
  const $ = (s, r) => (r || document).querySelector(s);
  const $$ = (s, r) => Array.from((r || document).querySelectorAll(s));
  const esc = (s) => (s || '').replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
  const ls = {
    get(k) { try { return localStorage.getItem(k); } catch (e) { return null; } },
    set(k, v) { try { localStorage.setItem(k, v); } catch (e) {} },
    del(k) { try { localStorage.removeItem(k); } catch (e) {} },
  };
  const html = document.documentElement;
  const slug = (location.pathname.match(/\/ep\/([^/]+)/) || [])[1];

  document.body.classList.add('epjs');

  /* ---------- 收听 / 阅读历史（首页「继续」用）：lex-hist = {slug: {t, d, rp, at}} ---------- */
  function histUpdate(patch) {
    if (!slug) return;
    let h = {};
    try { h = JSON.parse(ls.get('lex-hist') || '{}') || {}; } catch (e) {}
    h[slug] = Object.assign(h[slug] || {}, patch, { at: Date.now() });
    const keys = Object.keys(h).sort((a, b) => h[b].at - h[a].at);
    keys.slice(40).forEach((k) => delete h[k]);
    ls.set('lex-hist', JSON.stringify(h));
  }
  const histGet = () => { try { return (JSON.parse(ls.get('lex-hist') || '{}') || {})[slug] || {}; } catch (e) { return {}; } };

  /* ---------- 复制 RSS 订阅地址（页脚） ---------- */
  document.addEventListener('click', (e) => {
    const b = e.target.closest('[data-copy-feed]');
    if (!b) return;
    const url = location.origin + '/feed.xml';
    const copied = () => {
      b.textContent = '已复制';
      setTimeout(() => { b.textContent = '复制地址'; }, 1600);
    };
    if (navigator.clipboard && navigator.clipboard.writeText) {
      navigator.clipboard.writeText(url).then(copied).catch(() => { location.href = '/feed.xml'; });
    } else {
      location.href = '/feed.xml';
    }
  });

  /* ---------- 返回顶部 ---------- */
  const toTop = document.createElement('button');
  toTop.id = 'toTop';
  toTop.type = 'button';
  toTop.innerHTML = '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M12 19V5M5.5 11.5L12 5l6.5 6.5"/></svg>';
  toTop.setAttribute('aria-label', '回到顶部');
  toTop.addEventListener('click', () => window.scrollTo({ top: 0, behavior: 'smooth' }));
  document.body.appendChild(toTop);

  /* ---------- 内容 tab：中文精读 / 英文文稿 ---------- */
  const tabsRow = $('.tabs');
  const tabBtns = $$('.tab-btn');
  const panels = $$('.tab-panel');
  const article = $('.zh-article');
  let current = null;
  function activate(name) {
    current = name;
    tabBtns.forEach((b) => {
      const on = b.dataset.tab === name;
      b.classList.toggle('on', on);
      b.setAttribute('aria-selected', on);
    });
    panels.forEach((p) => p.classList.toggle('active', p.dataset.panel === name));
    syncTools();
  }

  /* ---------- 阅读工具（tabs 右端，与正文右边缘对齐）：目录 + 阅读设置 Aa ---------- */
  let tools, tocBtn, aaBtn, aaPop, tocPop, progress, aside;
  const heads = article ? $$('h2', article) : [];
  const SIZES = [15, 16, 17, 18, 19, 20, 21];
  let size = parseInt(getComputedStyle(html).getPropertyValue('--read-size'), 10) || 17;

  if (tabsRow && article) {
    tools = document.createElement('div');
    tools.className = 'tab-tools';
    tools.innerHTML =
      (heads.length > 2 ? `<button type="button" class="tool-btn" data-tool="toc" aria-expanded="false" aria-haspopup="true" title="目录">
        <svg viewBox="0 0 24 24" aria-hidden="true"><path d="M4 6h16M4 12h11M4 18h14"/></svg><span class="lbl">目录</span></button>` : '') +
      `<button type="button" class="tool-btn" data-tool="aa" aria-expanded="false" aria-haspopup="true" title="阅读设置：字体与字号">
        <span class="aa">A<small>a</small></span><span class="lbl">阅读设置</span></button>`;
    tabsRow.appendChild(tools);
    tocBtn = $('[data-tool="toc"]', tools);
    aaBtn = $('[data-tool="aa"]', tools);

    aaPop = document.createElement('div');
    aaPop.className = 'pop';
    aaPop.hidden = true;
    aaPop.setAttribute('role', 'dialog');
    aaPop.setAttribute('aria-label', '阅读设置');
    aaPop.innerHTML = `<div class="pop-row"><div class="pop-k">正文字体</div>
        <div class="seg" data-seg="font"><button type="button" data-v="sans">黑体</button><button type="button" class="serif" data-v="serif">宋体</button></div></div>
      <div class="pop-row"><div class="pop-k">字号</div>
        <div class="seg" data-seg="size"><button type="button" data-v="-1" aria-label="缩小字号">A−</button><span class="sz" role="status"></span><button type="button" data-v="1" aria-label="放大字号">A+</button></div></div>`;
    tabsRow.appendChild(aaPop);

    progress = document.createElement('div');
    progress.className = 'read-progress';
    tabsRow.appendChild(progress);

    const syncAa = () => {
      const serif = html.classList.contains('font-serif');
      $$('[data-seg="font"] button', aaPop).forEach((b) => b.setAttribute('aria-pressed', (b.dataset.v === 'serif') === serif));
      $('.sz', aaPop).textContent = size + ' px';
      const [dn, up] = $$('[data-seg="size"] button', aaPop);
      dn.disabled = size <= SIZES[0];
      up.disabled = size >= SIZES[SIZES.length - 1];
    };
    syncAa();
    aaPop.addEventListener('click', (e) => {
      const b = e.target.closest('button');
      if (!b) return;
      const seg = b.parentNode.dataset.seg;
      // 调整前记住视口内的锚点段落，避免字号变化后阅读位置跳走
      const stuck = tabsRow.getBoundingClientRect().top <= 1;
      const anchor = stuck && heads.concat($$('p', article)).find((el) => el.getBoundingClientRect().top > 60);
      const before = anchor ? anchor.getBoundingClientRect().top : 0;
      if (seg === 'font') {
        const serif = b.dataset.v === 'serif';
        html.classList.toggle('font-serif', serif);
        ls.set('lex-font', serif ? 'serif' : 'sans');
        if (window.umami) window.umami.track('font-toggle', { font: b.dataset.v });
      } else if (seg === 'size') {
        size = Math.min(SIZES[SIZES.length - 1], Math.max(SIZES[0], size + Number(b.dataset.v)));
        html.style.setProperty('--read-size', size + 'px');
        ls.set('lex-size', String(size));
      }
      if (anchor) window.scrollBy(0, anchor.getBoundingClientRect().top - before);
      syncAa();
    });

    /* 目录：宽屏放右侧固定侧栏，窄屏为弹出层 */
    if (heads.length > 2) {
      heads.forEach((h, i) => { if (!h.id) h.id = 's' + (i + 1); });
      const listHTML = '<ol class="toc-list">' + heads.map((h) => `<li><a href="#${h.id}">${esc(h.textContent)}</a></li>`).join('') + '</ol>';
      tocPop = document.createElement('div');
      tocPop.className = 'pop pop-toc';
      tocPop.hidden = true;
      tocPop.setAttribute('role', 'dialog');
      tocPop.setAttribute('aria-label', '目录');
      tocPop.innerHTML = listHTML;
      tabsRow.appendChild(tocPop);
      aside = $('.ep-toc');
      if (aside) aside.innerHTML = '<div class="toc-h">目录</div>' + listHTML;
      document.addEventListener('click', (e) => {
        const a = e.target.closest('.toc-list a');
        if (!a) return;
        e.preventDefault();
        const t = document.getElementById(a.getAttribute('href').slice(1));
        if (t) {
          t.scrollIntoView({ behavior: 'smooth', block: 'start' });
          history.replaceState(null, '', '#' + t.id);
        }
        closePops();
      });
    }

    const pops = [[aaBtn, aaPop], [tocBtn, tocPop]].filter((x) => x[0] && x[1]);
    function closePops(except) {
      pops.forEach(([b, p]) => { if (p !== except) { p.hidden = true; b.setAttribute('aria-expanded', 'false'); } });
    }
    pops.forEach(([b, p]) => b.addEventListener('click', (e) => {
      e.stopPropagation();
      const open = p.hidden;
      closePops(p);
      p.hidden = !open;
      b.setAttribute('aria-expanded', String(open));
      if (open && p === tocPop) { const on = $('a.on', p); if (on) on.scrollIntoView({ block: 'nearest' }); }
    }));
    document.addEventListener('click', (e) => { if (!e.target.closest('.pop')) closePops(); });
    document.addEventListener('keydown', (e) => { if (e.key === 'Escape') closePops(); });
  }

  const wide = window.matchMedia('(min-width: 1320px)');
  function syncTools() {
    const zhOn = current === 'zh';
    if (tools) tools.style.visibility = zhOn ? '' : 'hidden';
    if (progress) progress.style.display = zhOn ? '' : 'none';
    if (aside) {
      aside.hidden = !zhOn;
      document.body.classList.toggle('has-side-toc', zhOn && wide.matches);
    }
  }
  if (wide.addEventListener) wide.addEventListener('change', syncTools);

  if (tabBtns.length) {
    tabBtns.forEach((b) => b.addEventListener('click', () => {
      const y = tabsRow.getBoundingClientRect().top <= 1 ? window.scrollY : null;
      activate(b.dataset.tab);
      // 吸顶状态下切 tab，回到内容开头，而不是停在新 tab 的中段
      if (y !== null) window.scrollTo({ top: tabsRow.parentNode.offsetTop - 1 });
    }));
    activate(tabBtns[0].dataset.tab);
  }

  /* ---------- 滚动：返回顶部 / 阅读进度 / 目录高亮 / 记录读到哪 ---------- */
  let tick = false, lastSaved = 0;
  function onScroll() {
    tick = false;
    toTop.classList.toggle('show', window.scrollY > 600);
    if (!article || current !== 'zh') return;
    const r = article.getBoundingClientRect();
    const total = r.height - window.innerHeight * 0.6;
    const p = Math.min(1, Math.max(0, -r.top / (total > 0 ? total : 1)));
    if (progress) progress.style.transform = `scaleX(${p})`;
    if (heads.length > 2) {
      let idx = -1;
      for (let i = 0; i < heads.length; i++) { if (heads[i].getBoundingClientRect().top < 110) idx = i; else break; }
      $$('.toc-list a').forEach((a) => a.classList.toggle('on', idx >= 0 && a.getAttribute('href') === '#' + heads[idx].id));
    }
    if (Math.abs(p - lastSaved) > 0.02 && p > 0.03) { lastSaved = p; histUpdate({ rp: Math.round(p * 1000) / 1000 }); }
  }
  window.addEventListener('scroll', () => { if (!tick) { tick = true; requestAnimationFrame(onScroll); } }, { passive: true });
  onScroll();

  /* 继续阅读：上次读到中段时，给一个可点的提示，不自动跳 */
  if (article && !location.hash) {
    const rp = histGet().rp || 0;
    if (rp > 0.06 && rp < 0.95) {
      const toast = document.createElement('div');
      toast.className = 'mini-player resume-toast';
      toast.innerHTML = `<div class="mp-body"><div class="mp-title">上次读到 ${Math.round(rp * 100)}%</div></div>
        <button type="button" class="chip" data-go>继续阅读</button><button type="button" class="mp-close" aria-label="关闭">×</button>`;
      document.body.appendChild(toast);
      requestAnimationFrame(() => toast.classList.add('show'));
      const hide = () => { toast.classList.remove('show'); setTimeout(() => toast.remove(), 300); };
      $('[data-go]', toast).addEventListener('click', () => {
        if (current !== 'zh' && tabBtns.length) activate('zh');
        const r = article.getBoundingClientRect();
        window.scrollTo({ top: window.scrollY + r.top + rp * (r.height - window.innerHeight * 0.6), behavior: 'smooth' });
        hide();
      });
      $('.mp-close', toast).addEventListener('click', hide);
      setTimeout(hide, 9000);
    }
  }

  /* ---------- 视频点击加载（避免每页都拉 YouTube 脚本） ---------- */
  const facade = $('.video-facade');
  function openVideo() {
    if (!facade || !facade.isConnected) return;
    const f = document.createElement('iframe');
    f.src = `https://www.youtube.com/embed/${facade.dataset.yt}?autoplay=1&rel=0&origin=${encodeURIComponent(location.origin)}`;
    f.title = ($('.ep-title') || {}).textContent || 'Lex Fridman Podcast';
    f.allow = 'accelerometer; autoplay; encrypted-media; picture-in-picture';
    f.allowFullscreen = true;
    const media = facade.closest('.media');
    if (media) media.classList.add('video-open');
    facade.replaceWith(f);
    const a = $('audio');
    if (a && !a.paused) a.pause();
  }
  if (facade) facade.addEventListener('click', openVideo);

  /* ---------- 文稿：时间戳可点击跳播 + 站内搜索高亮（Enter / ↑↓ 跳到下一处） ---------- */
  const trText = $('.transcript-text');
  const toSec = (t) => {
    const p = t.split(':').map(Number);
    return p.length === 3 ? p[0] * 3600 + p[1] * 60 + p[2] : p[0] * 60 + p[1];
  };
  if (trText) {
    const stamped = esc(trText.textContent)
      .replace(/\[(\d{1,2}:\d{2}(?::\d{2})?)\]/g, (m, t) => `<span class="ts-link" data-t="${t}" title="跳转到 ${t}">${t}</span>`)
      .replace(/\((\d{1,2}:\d{2}:\d{2})\)/g, (m, t) => `<span class="ts-link" data-t="${t}" title="跳转到 ${t}">${t}</span>`);
    trText.innerHTML = stamped;
    const hasTs = !!$('.ts-link', trText);
    const tools2 = document.createElement('div');
    tools2.className = 'tr-tools';
    tools2.innerHTML = `<input class="tr-search" type="search" placeholder="在文稿中搜索…" autocomplete="off" aria-label="在文稿中搜索">
      <span class="tr-count" aria-live="polite"></span>${hasTs && $('audio') ? '<span class="tr-hint">点击时间戳可跳到音频对应位置</span>' : ''}`;
    trText.parentNode.insertBefore(tools2, trText);
    const inp = $('.tr-search', tools2);
    const cnt = $('.tr-count', tools2);
    const baseHTML = trText.innerHTML;
    let marks = [], cur = -1;
    const highlight = (q) => {
      const lq = q.toLowerCase();
      const walker = document.createTreeWalker(trText, NodeFilter.SHOW_TEXT);
      const targets = [];
      while (walker.nextNode()) {
        const node = walker.currentNode;
        if (node.nodeValue.toLowerCase().includes(lq)) targets.push(node);
      }
      targets.forEach((node) => {
        const frag = document.createDocumentFragment();
        const text = node.nodeValue;
        let i = 0, idx;
        const lower = text.toLowerCase();
        while ((idx = lower.indexOf(lq, i)) !== -1) {
          if (idx > i) frag.appendChild(document.createTextNode(text.slice(i, idx)));
          const mark = document.createElement('mark');
          mark.textContent = text.slice(idx, idx + q.length);
          frag.appendChild(mark);
          i = idx + q.length;
        }
        if (i < text.length) frag.appendChild(document.createTextNode(text.slice(i)));
        node.parentNode.replaceChild(frag, node);
      });
      return $$('mark', trText);
    };
    const go = (d) => {
      if (!marks.length) return;
      if (cur >= 0) marks[cur].classList.remove('cur');
      cur = (cur + d + marks.length) % marks.length;
      const m = marks[cur];
      m.classList.add('cur');
      trText.scrollTop += m.getBoundingClientRect().top - trText.getBoundingClientRect().top - trText.clientHeight / 3;
      $('.tr-pos', cnt).textContent = `${cur + 1} / ${marks.length}`;
    };
    let deb;
    inp.addEventListener('input', () => {
      clearTimeout(deb);
      deb = setTimeout(() => {
        const q = inp.value.trim();
        trText.innerHTML = baseHTML;
        marks = []; cur = -1;
        if (!q) { cnt.textContent = ''; return; }
        marks = highlight(q);
        if (!marks.length) { cnt.textContent = '无匹配'; return; }
        cnt.innerHTML = `<span class="tr-pos"></span><button type="button" data-d="-1" aria-label="上一处">↑</button><button type="button" data-d="1" aria-label="下一处">↓</button>`;
        go(1);
      }, 180);
    });
    inp.addEventListener('keydown', (e) => {
      if (e.key === 'Enter') { e.preventDefault(); go(e.shiftKey ? -1 : 1); }
    });
    cnt.addEventListener('click', (e) => { const b = e.target.closest('button'); if (b) go(Number(b.dataset.d)); });
  }

  /* ---------- 音频播放器 ---------- */
  const ap = $('.audio-player');
  if (!ap) return;
  const audio = $('audio', ap);
  const lsKey = 'lex-pos-' + ap.dataset.slug;
  const playBtn = $('.ap-play', ap);
  const curEl = $('.ap-cur', ap);
  const durEl = $('.ap-dur', ap);
  const bufEl = $('.ap-buf', ap);
  const fillEl = $('.ap-fill', ap);
  const bar = $('.ap-bar', ap);
  const rateBtn = $('.ap-rate', ap);
  const resumeChip = $('.ap-resume', ap);

  const RATES = [1, 1.25, 1.5, 1.75, 2];
  let rateIdx = Math.max(0, RATES.indexOf(Number(ls.get('lex-rate')) || 1));
  let seeking = false;

  /* 手机端：视频缩略图收进播放器里的「视频」按钮 */
  if (facade && ap.closest('.media')) {
    const vb = document.createElement('button');
    vb.type = 'button';
    vb.className = 'ap-video';
    vb.innerHTML = '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M8 5.5v13a1 1 0 0 0 1.5.86l10.6-6.5a1 1 0 0 0 0-1.72L9.5 4.64A1 1 0 0 0 8 5.5z"/></svg>视频';
    vb.addEventListener('click', () => { openVideo(); vb.remove(); });
    $('.ap-line2', ap).insertBefore(vb, rateBtn.nextSibling);
  }

  function track(name) { if (window.umami) window.umami.track(name, { slug: ap.dataset.slug }); }
  function save() {
    if (audio.currentTime > 5) {
      ls.set(lsKey, String(Math.floor(audio.currentTime)));
      histUpdate({ t: Math.floor(audio.currentTime), d: isFinite(audio.duration) ? Math.floor(audio.duration) : undefined });
    }
  }
  const fmt = (t) => {
    if (!isFinite(t)) return '--:--';
    t = Math.max(0, Math.round(t));
    const h = Math.floor(t / 3600), m = Math.floor((t % 3600) / 60), s = t % 60;
    const mm = String(m).padStart(2, '0'), ss = String(s).padStart(2, '0');
    return h ? `${h}:${mm}:${ss}` : `${m}:${ss}`;
  };
  function setFill() {
    curEl.textContent = fmt(audio.currentTime);
    if (isFinite(audio.duration) && audio.duration > 0) {
      fillEl.style.width = (audio.currentTime / audio.duration * 100) + '%';
      bar.setAttribute('aria-valuenow', Math.round(audio.currentTime));
      bar.setAttribute('aria-valuetext', `${fmt(audio.currentTime)} / ${fmt(audio.duration)}`);
    }
  }
  const setRate = () => { audio.playbackRate = RATES[rateIdx]; rateBtn.textContent = RATES[rateIdx] + '×'; };
  setRate();

  /* 断点续听：>30s 且未播完时自动跳到上次位置，8 秒后提示条自动隐藏 */
  const saved = +(ls.get(lsKey) || 0);
  if (saved > 30) curEl.textContent = fmt(saved);
  audio.addEventListener('loadedmetadata', () => {
    durEl.textContent = fmt(audio.duration);
    bar.setAttribute('aria-valuemax', Math.round(audio.duration));
    if (saved > 30 && saved < audio.duration - 10 && audio.currentTime < 1) {
      audio.currentTime = saved;
      resumeChip.hidden = false;
      setTimeout(() => { resumeChip.hidden = true; }, 8000);
    }
    setRate();
  });
  $('.ap-restart', ap).addEventListener('click', () => { audio.currentTime = 0; resumeChip.hidden = true; });

  const togglePlay = () => (audio.paused ? audio.play() : audio.pause());
  playBtn.addEventListener('click', togglePlay);
  audio.addEventListener('play', () => {
    document.body.classList.add('is-playing');
    playBtn.setAttribute('aria-label', '暂停');
    track('play-audio');
  });
  audio.addEventListener('pause', () => {
    document.body.classList.remove('is-playing');
    playBtn.setAttribute('aria-label', '播放');
    save();
  });
  audio.addEventListener('ended', () => { ls.del(lsKey); histUpdate({ t: 0, done: 1 }); });
  audio.addEventListener('timeupdate', () => {
    if (!seeking) setFill();
    mpFill.style.width = (audio.currentTime / (audio.duration || 1) * 100) + '%';
    mpTime.textContent = fmt(audio.currentTime);
  });
  audio.addEventListener('progress', () => {
    try {
      const b = audio.buffered;
      if (b.length && isFinite(audio.duration)) bufEl.style.width = (b.end(b.length - 1) / audio.duration * 100) + '%';
    } catch (e) {}
  });
  setInterval(() => { if (!audio.paused) save(); }, 5000);
  window.addEventListener('pagehide', save);

  /* 进度条拖拽 / 点击 seek */
  function seekAt(ev) {
    const r = bar.getBoundingClientRect();
    const p = Math.min(1, Math.max(0, ((ev.clientX || 0) - r.left) / r.width));
    if (isFinite(audio.duration)) audio.currentTime = p * audio.duration;
  }
  bar.setAttribute('aria-valuemin', '0');
  bar.addEventListener('pointerdown', (ev) => { seeking = true; bar.setPointerCapture(ev.pointerId); seekAt(ev); });
  bar.addEventListener('pointermove', (ev) => { if (seeking) seekAt(ev); });
  bar.addEventListener('pointerup', () => { seeking = false; setFill(); });
  bar.addEventListener('keydown', (ev) => {
    if (ev.key === 'ArrowLeft') { ev.preventDefault(); audio.currentTime = Math.max(0, audio.currentTime - 10); }
    if (ev.key === 'ArrowRight') { ev.preventDefault(); audio.currentTime += 10; }
  });

  $$('.ap-skip', ap).forEach((b) => b.addEventListener('click', () => {
    audio.currentTime = Math.max(0, (audio.currentTime || 0) + Number(b.dataset.s));
  }));
  rateBtn.addEventListener('click', () => {
    rateIdx = (rateIdx + 1) % RATES.length;
    setRate();
    ls.set('lex-rate', String(RATES[rateIdx]));
  });

  /* ---------- 文稿时间戳点击 → 跳播 ---------- */
  if (trText) {
    trText.addEventListener('click', (e) => {
      const el = e.target.closest('.ts-link');
      if (!el) return;
      const s = toSec(el.dataset.t);
      if (!isFinite(s)) return;
      audio.currentTime = s;
      if (audio.paused) audio.play().catch(() => {});
      track('ts-seek');
    });
  }

  /* ---------- 键盘快捷键：空格播放/暂停，←/→ 快退快进 10s ---------- */
  document.addEventListener('keydown', (e) => {
    if (e.metaKey || e.ctrlKey || e.altKey) return;
    const t = e.target;
    if (t && t.closest && t.closest('input, textarea, select, button, a, [contenteditable], [role="slider"]')) return;
    if (e.key === ' ') {
      e.preventDefault();
      togglePlay();
    } else if (e.key === 'ArrowLeft') {
      audio.currentTime = Math.max(0, audio.currentTime - 10);
    } else if (e.key === 'ArrowRight') {
      audio.currentTime += 10;
    }
  });

  /* ---------- 迷你悬浮条：播放中且主播放器滚出视口时出现 ---------- */
  const mini = document.createElement('div');
  mini.className = 'mini-player';
  mini.innerHTML = `<button type="button" class="mp-play" aria-label="播放/暂停">${playBtn.innerHTML}</button>
    <div class="mp-body"><div class="mp-title">${esc(ap.dataset.title)}</div>
    <div class="mp-row"><div class="mp-bar"><div class="mp-fill"></div></div><span class="mp-time"></span></div></div>
    <button type="button" class="mp-close" aria-label="关闭迷你播放器">×</button>`;
  document.body.appendChild(mini);
  const mpFill = $('.mp-fill', mini);
  const mpTime = $('.mp-time', mini);
  let miniDismissed = false, apVisible = true, started = false;
  const syncMini = () => {
    const should = started && !apVisible && !miniDismissed;
    mini.classList.toggle('show', should);
    document.body.classList.toggle('mini-on', should);
  };
  $('.mp-close', mini).addEventListener('click', () => { miniDismissed = true; syncMini(); });
  $('.mp-play', mini).addEventListener('click', togglePlay);
  audio.addEventListener('play', () => { started = true; miniDismissed = false; syncMini(); });
  audio.addEventListener('pause', syncMini);
  new IntersectionObserver((entries) => { apVisible = entries[0].isIntersecting; syncMini(); }, { threshold: 0 }).observe(ap);
})();
