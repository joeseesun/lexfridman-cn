/* Lex Fridman 播客 · 单集页：tab 切换 / 视频懒加载 / 官方音频播放器 */
(function () {
  'use strict';
  const $ = (s, r) => (r || document).querySelector(s);
  const $$ = (s, r) => Array.from((r || document).querySelectorAll(s));
  const esc = (s) => (s || '').replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));

  document.body.classList.add('epjs');

  /* ---------- 精读字体切换（黑体 / 宋体）+ 复制 RSS 订阅地址 ---------- */
  try { if (localStorage.getItem('lex-font') === 'serif') document.documentElement.classList.add('font-serif'); } catch (e) {}
  const tabsRow = document.querySelector('.tabs');
  if (tabsRow && document.getElementById('panel-zh')) {
    const fbtn = document.createElement('button');
    fbtn.type = 'button';
    fbtn.className = 'font-toggle';
    fbtn.title = '切换精读正文字体（黑体 / 宋体）';
    const fontLabel = () => { fbtn.textContent = document.documentElement.classList.contains('font-serif') ? '黑体' : '宋体'; };
    fontLabel();
    fbtn.addEventListener('click', () => {
      const serif = document.documentElement.classList.toggle('font-serif');
      fontLabel();
      try { localStorage.setItem('lex-font', serif ? 'serif' : 'sans'); } catch (e) {}
      if (window.umami) window.umami.track('font-toggle');
    });
    tabsRow.appendChild(fbtn);
  }

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
  toTop.innerHTML = '↑';
  toTop.setAttribute('aria-label', '回到顶部');
  toTop.addEventListener('click', () => window.scrollTo({ top: 0, behavior: 'smooth' }));
  document.body.appendChild(toTop);
  let ttTick = false;
  window.addEventListener('scroll', () => {
    if (ttTick) return;
    ttTick = true;
    requestAnimationFrame(() => { toTop.classList.toggle('show', window.scrollY > 600); ttTick = false; });
  }, { passive: true });

  /* ---------- 内容 tab：中文精读 / 英文文稿 ---------- */
  const tabBtns = $$('.tab-btn');
  const panels = $$('.tab-panel');
  function activate(name) {
    tabBtns.forEach((b) => {
      const on = b.dataset.tab === name;
      b.classList.toggle('on', on);
      b.setAttribute('aria-selected', on);
    });
    panels.forEach((p) => p.classList.toggle('active', p.dataset.panel === name));
  }
  if (tabBtns.length) {
    tabBtns.forEach((b) => b.addEventListener('click', () => activate(b.dataset.tab)));
    activate(tabBtns[0].dataset.tab);
  }

  /* ---------- 视频点击加载（避免每页都拉 YouTube 脚本） ---------- */
  $$('.video-facade').forEach((v) => {
    const go = () => {
      const f = document.createElement('iframe');
      f.src = `https://www.youtube.com/embed/${v.dataset.yt}?autoplay=1&rel=0&origin=${encodeURIComponent(location.origin)}`;
      f.title = v.querySelector('img') ? v.querySelector('img').alt : 'Lex Fridman Podcast';
      f.allow = 'accelerometer; autoplay; encrypted-media; picture-in-picture';
      f.allowFullscreen = true;
      v.replaceWith(f);
    };
    v.addEventListener('click', go);
    v.addEventListener('keydown', (e) => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); go(); } });
  });

  /* ---------- 文稿：时间戳可点击跳播 + 站内搜索高亮 ---------- */
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
    const tools = document.createElement('div');
    tools.className = 'tr-tools';
    tools.innerHTML = `<input class="tr-search" type="search" placeholder="在文稿中搜索…" autocomplete="off" aria-label="在文稿中搜索">
      <span class="tr-count" aria-live="polite"></span><span class="tr-hint">时间戳可点击跳转音频</span>`;
    trText.parentNode.insertBefore(tools, trText);
    const inp = $('.tr-search', tools);
    const cnt = $('.tr-count', tools);
    const baseHTML = trText.innerHTML;
    const highlight = (q) => {
      const lq = q.toLowerCase();
      let n = 0;
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
          n++;
          i = idx + q.length;
        }
        if (i < text.length) frag.appendChild(document.createTextNode(text.slice(i)));
        node.parentNode.replaceChild(frag, node);
      });
      return n;
    };
    let deb;
    inp.addEventListener('input', () => {
      clearTimeout(deb);
      deb = setTimeout(() => {
        const q = inp.value.trim();
        trText.innerHTML = baseHTML;
        if (!q) { cnt.textContent = ''; return; }
        const n = highlight(q);
        cnt.textContent = n ? `${n} 处匹配` : '无匹配';
      }, 180);
    });
  }

  /* ---------- 音频播放器 ---------- */
  const ap = $('.audio-player');
  if (!ap) return;
  const audio = $('audio', ap);
  const slug = ap.dataset.slug;
  const lsKey = 'lex-pos-' + slug;
  const playBtn = $('.ap-play', ap);
  const curEl = $('.ap-cur', ap);
  const durEl = $('.ap-dur', ap);
  const bufEl = $('.ap-buf', ap);
  const fillEl = $('.ap-fill', ap);
  const bar = $('.ap-bar', ap);
  const rateBtn = $('.ap-rate', ap);
  const resumeChip = $('.ap-resume', ap);

  const RATES = [1, 1.25, 1.5, 1.75, 2];
  let rateIdx = 0;
  let seeking = false;

  function track(name) { if (window.umami) window.umami.track(name, { slug }); }
  function save() { try { if (audio.currentTime > 5) localStorage.setItem(lsKey, Math.floor(audio.currentTime)); } catch (e) {} }
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
    }
  }

  /* 断点续听：>30s 且未播完时自动跳到上次位置，8 秒后提示条自动隐藏 */
  const saved = +(() => { try { return localStorage.getItem(lsKey) || 0; } catch (e) { return 0; } })();
  audio.addEventListener('loadedmetadata', () => {
    durEl.textContent = fmt(audio.duration);
    if (saved > 30 && saved < audio.duration - 10) {
      audio.currentTime = saved;
      resumeChip.hidden = false;
      setTimeout(() => { resumeChip.hidden = true; }, 8000);
    }
  });
  $('.ap-restart', ap).addEventListener('click', () => { audio.currentTime = 0; resumeChip.hidden = true; });

  playBtn.addEventListener('click', () => (audio.paused ? audio.play() : audio.pause()));
  audio.addEventListener('play', () => {
    playBtn.textContent = '❚❚'; playBtn.setAttribute('aria-label', '暂停');
    document.body.classList.add('ap-playing');
    track('play-audio');
  });
  audio.addEventListener('pause', () => {
    playBtn.textContent = '▶'; playBtn.setAttribute('aria-label', '播放');
    document.body.classList.remove('ap-playing');
    save();
  });
  audio.addEventListener('ended', () => { try { localStorage.removeItem(lsKey); } catch (e) {} });
  audio.addEventListener('timeupdate', () => { if (!seeking) setFill(); mpFill.style.width = (audio.currentTime / (audio.duration || 1) * 100) + '%'; });
  audio.addEventListener('progress', () => {
    try {
      const b = audio.buffered;
      if (b.length && isFinite(audio.duration)) bufEl.style.width = (b.end(b.length - 1) / audio.duration * 100) + '%';
    } catch (e) {}
  });
  setInterval(save, 5000);
  window.addEventListener('pagehide', save);

  /* 进度条拖拽 / 点击 seek */
  function seekAt(ev) {
    const r = bar.getBoundingClientRect();
    const p = Math.min(1, Math.max(0, ((ev.clientX || 0) - r.left) / r.width));
    if (isFinite(audio.duration)) audio.currentTime = p * audio.duration;
  }
  bar.addEventListener('pointerdown', (ev) => { seeking = true; bar.setPointerCapture(ev.pointerId); seekAt(ev); });
  bar.addEventListener('pointermove', (ev) => { if (seeking) seekAt(ev); });
  bar.addEventListener('pointerup', () => { seeking = false; setFill(); });
  bar.addEventListener('keydown', (ev) => {
    if (ev.key === 'ArrowLeft') audio.currentTime = Math.max(0, audio.currentTime - 10);
    if (ev.key === 'ArrowRight') audio.currentTime += 10;
  });

  $$('.ap-skip', ap).forEach((b) => b.addEventListener('click', () => {
    audio.currentTime = Math.max(0, (audio.currentTime || 0) + Number(b.dataset.s));
  }));
  rateBtn.addEventListener('click', () => {
    rateIdx = (rateIdx + 1) % RATES.length;
    audio.playbackRate = RATES[rateIdx];
    rateBtn.textContent = RATES[rateIdx] + '×';
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
    if (t && t.closest && t.closest('input, textarea, select, button, a, [contenteditable]')) return;
    if (e.key === ' ') {
      e.preventDefault();
      if (audio.paused) audio.play(); else audio.pause();
    } else if (e.key === 'ArrowLeft') {
      audio.currentTime = Math.max(0, audio.currentTime - 10);
    } else if (e.key === 'ArrowRight') {
      audio.currentTime += 10;
    }
  });

  /* ---------- 迷你悬浮条：播放中且主播放器滚出视口时出现 ---------- */
  const mini = document.createElement('div');
  mini.className = 'mini-player';
  mini.innerHTML = `<button class="mp-play" aria-label="播放/暂停">▶</button>
    <div class="mp-body"><div class="mp-title">${esc(ap.dataset.title)}</div>
    <div class="mp-bar"><div class="mp-fill"></div></div></div>
    <button class="mp-close" aria-label="关闭迷你播放器">×</button>`;
  document.body.appendChild(mini);
  const mpPlay = $('.mp-play', mini);
  const mpFill = $('.mp-fill', mini);
  let miniDismissed = false;
  $('.mp-close', mini).addEventListener('click', () => { miniDismissed = true; mini.classList.remove('show'); });
  mpPlay.addEventListener('click', () => (audio.paused ? audio.play() : audio.pause()));
  const syncIcons = () => { mpPlay.textContent = playBtn.textContent; };
  audio.addEventListener('play', syncIcons);
  audio.addEventListener('pause', syncIcons);
  const io = new IntersectionObserver((entries) => {
    const should = document.body.classList.contains('ap-playing') && !entries[0].isIntersecting && !miniDismissed;
    mini.classList.toggle('show', should);
  }, { threshold: 0 });
  io.observe(ap);
})();
