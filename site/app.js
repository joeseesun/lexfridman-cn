/* Lex Fridman 播客全访谈 · 首页列表：搜索 / 筛选 / 排序 / 继续收听 */
(function () {
  'use strict';
  const $ = (s) => document.querySelector(s);
  const $$ = (s) => Array.from(document.querySelectorAll(s));
  let DATA = [];
  let HIST = {};
  const state = { q: '', f: 'all', sort: 'desc' };
  let LIST = [];
  let rendered = 0;
  const PAGE = 30;
  const grid = $('#grid');
  const input = $('#search');

  const ls = {
    get(k) { try { return localStorage.getItem(k); } catch (e) { return null; } },
    set(k, v) { try { localStorage.setItem(k, v); } catch (e) {} },
    del(k) { try { localStorage.removeItem(k); } catch (e) {} },
  };

  /* 返回顶部 */
  const toTop = document.createElement('button');
  toTop.id = 'toTop';
  toTop.type = 'button';
  toTop.innerHTML = '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M12 19V5M5.5 11.5L12 5l6.5 6.5"/></svg>';
  toTop.setAttribute('aria-label', '回到顶部');
  toTop.addEventListener('click', () => window.scrollTo({ top: 0, behavior: 'smooth' }));
  document.body.appendChild(toTop);
  let ttTick = false;
  window.addEventListener('scroll', () => {
    if (ttTick) return;
    ttTick = true;
    requestAnimationFrame(() => { toTop.classList.toggle('show', window.scrollY > 600); ttTick = false; });
  }, { passive: true });

  /* 旧 hash 链接（#/slug）跳转到真实单集页 */
  function legacyRedirect() {
    const m = location.hash.match(/^#\/([^/]+)$/);
    if (m) location.replace('/ep/' + m[1] + '/');
  }

  function esc(s) {
    return (s || '').replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
  }

  /* ---------- 搜索：归一化 + 多词 AND + 加权排序 ---------- */
  // 全角转半角、去重音、去标点与空格（「安德鲁斯卡尔」也能命中「安德鲁·斯卡尔」）
  const PUNCT = /[\s·•・\-–—_'’"“”:：,，.。!！?？()（）\[\]【】#&/、|]+/g;
  const norm = (s) => (s || '').normalize('NFKD').replace(/[̀-ͯ]/g, '').toLowerCase().replace(PUNCT, '');
  const stripNum = (t) => (t || '').replace(/^#\d+\s*[–—:-]?\s*/, '');

  function indexEntry(e) {
    e._zh = stripNum(e.zh) || stripNum(e.t);
    e._en = stripNum(e.t);
    const head = (t) => (t || '').split(/[:：]/)[0];
    e._f = {
      // 嘉宾名通常在标题冒号前，命中它比命中正文话题更相关
      guest: norm(e.guest) + '|' + norm(head(e._zh)) + '|' + norm(head(e._en)),
      title: norm(e._zh + ' ' + e._en),
      slug: norm(e.s),
      desc: norm(e.ds),
    };
  }

  function tokens(q) {
    return q.trim().split(/\s+/).map(norm).filter(Boolean);
  }

  function score(e, toks, numQ) {
    if (numQ != null && e.n === numQ) return 1000;
    let total = 0;
    for (const t of toks) {
      const f = e._f;
      let s = 0;
      if (f.guest.includes(t)) s = 40;
      else if (f.title.includes(t)) s = 30;
      else if (f.slug.includes(t)) s = 20;
      else if (f.desc.includes(t)) s = 10;
      else if (/^\d+$/.test(t) && e.n != null && String(e.n).startsWith(t)) s = 5;
      if (!s) return 0;
      total += s;
    }
    return total;
  }

  function compute() {
    const toks = tokens(state.q);
    const m = state.q.trim().match(/^#?(\d{1,3})$/);
    const numQ = m ? Number(m[1]) : null;
    let list = DATA.filter((e) => {
      if (state.f === 'zh' && !e.r) return false;
      if (state.f === 'tr' && !e.tr) return false;
      if (state.f === 'hist' && !HIST[e.s]) return false;
      return true;
    });
    const dir = state.sort === 'asc' ? -1 : 1;
    if (toks.length) {
      list = list.map((e) => [e, score(e, toks, numQ)]).filter((x) => x[1] > 0)
        .sort((a, b) => (b[1] - a[1]) || dir * (a[0]._i - b[0]._i))
        .map((x) => x[0]);
    } else if (state.f === 'hist') {
      list.sort((a, b) => (HIST[b.s].at || 0) - (HIST[a.s].at || 0));
    } else if (dir === -1) {
      list = list.slice().reverse();
    }
    LIST = list;
    return toks;
  }

  // 把命中词在原文中高亮（只处理能在原文中直接找到的词）
  function hl(text, toks) {
    let out = esc(text);
    if (!toks.length || !text) return out;
    const raw = state.q.trim().split(/\s+/).filter((t) => t.length > 0 && !/^#?\d+$/.test(t));
    if (!raw.length) return out;
    const re = new RegExp('(' + raw.map((t) => esc(t).replace(/[.*+?^${}()|[\]\\]/g, '\\$&')).join('|') + ')', 'gi');
    return out.replace(/(<[^>]+>)|([^<]+)/g, (m, tag, txt) => tag || txt.replace(re, '<mark>$1</mark>'));
  }

  const fmtT = (t) => {
    t = Math.max(0, Math.round(t || 0));
    const h = Math.floor(t / 3600), m = Math.floor((t % 3600) / 60);
    return h ? `${h} 小时 ${m} 分` : `${m} 分钟`;
  };

  function progressOf(e) {
    const h = HIST[e.s];
    if (!h || h.done) return 0;
    if (h.t && h.d) return Math.min(1, h.t / h.d);
    return h.rp || 0;
  }

  function cardHTML(e, toks) {
    const thumb = e.y
      ? `<img loading="lazy" decoding="async" src="https://i.ytimg.com/vi/${e.y}/mqdefault.jpg" alt="" width="320" height="180">`
      : '<div class="no-img">LEX</div>';
    const num = e.n != null ? `第 ${e.n} 期` : '特别节目';
    const date = e.d ? e.d.slice(0, 7).replace('-', '.') : '';
    const p = progressOf(e);
    const prog = p > 0.01 ? `<span class="prog" aria-hidden="true"><i style="width:${(p * 100).toFixed(1)}%"></i></span>` : '';
    const en = e.zh ? `<div class="card-title-en">${hl(e._en, toks)}</div>` : '';
    const desc = toks.length && e.ds ? `<div class="card-desc">${hl(e.ds, toks)}</div>` : '';
    return `<a class="card" href="/ep/${e.s}/">
      <div class="thumb">${thumb}${prog}</div>
      <div class="card-body">
        <div class="card-kicker"><span class="ep-n">${num}</span><span>${date}</span>${e.r ? '<span class="zh-tag">中文精读</span>' : ''}</div>
        <div class="card-title">${hl(e._zh, toks)}</div>
        ${en}${desc}
      </div>
    </a>`;
  }

  let curToks = [];
  function resetRender() {
    curToks = compute();
    rendered = 0;
    AUTO = 90;
    grid.innerHTML = '';
    syncURL();
    renderHero();
    renderContinue();
    renderResultLine();
    if (!LIST.length) {
      grid.innerHTML = emptyHTML();
      $('#sentinel').textContent = '';
      return;
    }
    renderMore();
  }

  function renderMore() {
    const slice = LIST.slice(rendered, rendered + PAGE);
    if (slice.length) {
      grid.insertAdjacentHTML('beforeend', slice.map((e) => cardHTML(e, curToks)).join(''));
      rendered += slice.length;
    }
    const sen = $('#sentinel');
    if (rendered >= LIST.length) sen.innerHTML = LIST.length > 6 ? '<span class="end">— 全部 ' + LIST.length + ' 期 —</span>' : '';
    else if (rendered >= AUTO) sen.innerHTML = `<button type="button" class="more-btn" data-more>再看 30 期</button><span class="more-sub">已显示 ${rendered} / ${LIST.length} 期 · <a href="/archive/">按年份浏览全部</a></span>`;
    else sen.textContent = '加载中…';
  }

  function renderResultLine() {
    const el = $('#resultLine');
    const filtered = state.q.trim() || state.f !== 'all';
    const label = { zh: '中文精读', tr: '有文稿', hist: '看过的' }[state.f];
    if (filtered) {
      el.innerHTML = `<h2>${state.q.trim() ? '搜索结果' : label}<small>${LIST.length} 期${state.q.trim() ? `与「${esc(state.q.trim())}」相关` : ''}</small></h2>`;
    } else {
      el.innerHTML = `<h2>全部单集<small>${state.sort === 'asc' ? '从第 1 期开始' : '最新在前'}</small></h2>`;
    }
  }

  const SUGGEST = ['Elon Musk', 'AI', '物理', '历史', 'Sam Altman', '意识', '编程'];
  function emptyHTML() {
    const q = state.q.trim();
    const chips = SUGGEST.map((s) => `<button type="button" class="chip" data-q="${esc(s)}">${esc(s)}</button>`).join('');
    const reset = state.f !== 'all' ? '<button type="button" class="chip" data-reset>在全部单集中搜索</button>' : '';
    return `<div class="empty"><h3>没有找到${q ? `「${esc(q)}」` : '符合条件的单集'}</h3>
      <p>试试嘉宾英文名、中文译名或话题关键词，多个词用空格分开。</p>
      <div class="chips">${reset}${chips}</div></div>`;
  }

  if (grid) grid.addEventListener('click', (e) => {
    const c = e.target.closest('[data-q]');
    if (c) { input.value = c.dataset.q; setFilter('all'); state.q = c.dataset.q; syncSearchBox(); resetRender(); return; }
    if (e.target.closest('[data-reset]')) { setFilter('all'); resetRender(); }
  });

  /* ---------- 报头：今日日期 + 收录概况 ---------- */
  function renderMast() {
    const md = $('#mastDate');
    if (md) {
      const t = new Date();
      md.textContent = `${t.getFullYear()} 年 ${t.getMonth() + 1} 月 ${t.getDate()} 日 · 星期${'日一二三四五六'[t.getDay()]}`;
    }
    const ms = $('#mastSub');
    if (ms) {
      const nZh = DATA.filter((x) => x.r).length;
      const since = DATA.map((x) => x.d).filter(Boolean).sort()[0];
      ms.textContent = `${DATA.length} 期深度访谈 · ${nZh} 篇中文精读${since ? ` · ${since.slice(0, 4)} 年至今` : ''}`;
    }
  }

  /* ---------- 头条：最新一篇中文精读 ---------- */
  function renderHero() {
    const box = $('#hero');
    if (!box) return;
    const e = DATA.find((x) => x.r);
    if (!e || state.q.trim() || state.f !== 'all') { box.hidden = true; return; }
    if (box.dataset.s === e.s) { box.hidden = false; return; }
    box.dataset.s = e.s;
    const d = e.d ? `${e.d.slice(0, 4)} 年 ${+e.d.slice(5, 7)} 月` : '';
    const img = e.y
      ? `<img src="https://i.ytimg.com/vi/${e.y}/maxresdefault.jpg" alt="" onerror="this.onerror=null;this.src='https://i.ytimg.com/vi/${e.y}/hqdefault.jpg'">`
      : '';
    const by = [e.guest, d, e.n != null ? `第 ${e.n} 期` : ''].filter(Boolean).map(esc).join(' · ');
    box.innerHTML = `<a class="hero-media" href="/ep/${e.s}/" tabindex="-1" aria-hidden="true">${img}</a>
      <div class="hero-text">
        <div class="hero-kicker">最新精读</div>
        <h2 class="hero-title"><a href="/ep/${e.s}/">${esc(e._zh)}</a></h2>
        <p class="hero-en">${esc(e._en)}</p>
        ${e.ds ? `<p class="hero-desc">${esc(e.ds)}</p>` : ''}
        <p class="hero-by">${by}</p>
        <a class="hero-cta" href="/ep/${e.s}/">阅读全文<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M5 12h14M13 6l6 6-6 6"/></svg></a>
      </div>`;
    box.hidden = false;
  }

  /* ---------- 继续收听 / 阅读 ---------- */
  function loadHist() {
    try { HIST = JSON.parse(ls.get('lex-hist') || '{}') || {}; } catch (e) { HIST = {}; }
    // 兼容旧版只存了 lex-pos-* 的收听进度
    try {
      Object.keys(localStorage).forEach((k) => {
        if (k.indexOf('lex-pos-') === 0) {
          const s = k.slice(8);
          if (!HIST[s]) HIST[s] = { t: +ls.get(k) || 0, at: 0 };
        }
      });
    } catch (e) {}
  }

  function renderContinue() {
    const box = $('#continue');
    const bySlug = {};
    DATA.forEach((e) => { bySlug[e.s] = e; });
    const items = Object.keys(HIST)
      .filter((s) => bySlug[s] && !HIST[s].done && ((HIST[s].t || 0) > 30 || ((HIST[s].rp || 0) > 0.05 && (HIST[s].rp || 0) < 0.95)))
      .sort((a, b) => (HIST[b].at || 0) - (HIST[a].at || 0))
      .slice(0, 4);
    if (!items.length || state.q.trim() || state.f !== 'all') { box.hidden = true; return; }
    box.hidden = false;
    $('#contRow').innerHTML = items.map((s) => {
      const e = bySlug[s], h = HIST[s];
      const p = progressOf(e);
      const meta = h.t > 30
        ? `听到 ${fmtT(h.t)}${h.d ? ` · 剩 ${fmtT(h.d - h.t)}` : ''}`
        : `读到 ${Math.round((h.rp || 0) * 100)}%`;
      const img = e.y ? `<img loading="lazy" src="https://i.ytimg.com/vi/${e.y}/mqdefault.jpg" alt="">` : '';
      return `<a class="cont-item" href="/ep/${e.s}/">
        <div class="cont-thumb">${img}<span class="prog"><i style="width:${(p * 100).toFixed(1)}%"></i></span></div>
        <div class="cont-body"><div class="cont-title">${esc(e._zh)}</div><div class="cont-meta">${meta}</div></div></a>`;
    }).join('');
  }
  function clearHist() {
    Object.keys(HIST).forEach((s) => ls.del('lex-pos-' + s));
    ls.del('lex-hist');
    HIST = {};
    updateCounts();
    resetRender();
  }

  /* ---------- 状态 ↔ URL（可分享、可后退） ---------- */
  function syncURL() {
    const p = new URLSearchParams();
    if (state.q.trim()) p.set('q', state.q.trim());
    if (state.f !== 'all') p.set('f', state.f);
    if (state.sort !== 'desc') p.set('sort', state.sort);
    const qs = p.toString();
    const url = location.pathname + (qs ? '?' + qs : '');
    if (url !== location.pathname + location.search) history.replaceState(null, '', url);
  }
  function readURL() {
    const p = new URLSearchParams(location.search);
    state.q = p.get('q') || '';
    state.f = ['zh', 'tr', 'hist'].includes(p.get('f')) ? p.get('f') : 'all';
    state.sort = p.get('sort') === 'asc' ? 'asc' : 'desc';
    input.value = state.q;
  }

  function setFilter(f) {
    state.f = f;
    $$('#filters button').forEach((x) => {
      const on = x.dataset.f === f;
      x.classList.toggle('on', on);
      x.setAttribute('aria-pressed', on);
    });
  }
  function syncSort() {
    const b = $('#sort');
    b.dataset.dir = state.sort;
    b.querySelector('span').textContent = state.sort === 'asc' ? '最早' : '最新';
    b.title = state.sort === 'asc' ? '当前：从第 1 期开始' : '当前：最新一期在前';
  }
  function syncSearchBox() { input.parentNode.classList.toggle('has-q', !!input.value); }

  function updateCounts() {
    const n = { zh: DATA.filter((e) => e.r).length, tr: DATA.filter((e) => e.tr).length, hist: DATA.filter((e) => HIST[e.s]).length };
    $$('[data-n]').forEach((el) => { el.textContent = n[el.dataset.n]; });
    $('[data-f="tr"]').hidden = n.tr === DATA.length || !n.tr;
    $('[data-f="hist"]').hidden = !n.hist;
    if (state.f === 'hist' && !n.hist) setFilter('all');
  }

  async function init() {
    legacyRedirect();
    readURL();
    syncSearchBox();
    syncSort();
    setFilter(state.f);

    const res = await fetch('data/episodes.json');
    DATA = (await res.json()).episodes;
    DATA.forEach((e, i) => { e._i = i; indexEntry(e); });
    loadHist();
    updateCounts();
    renderMast();
    $('#contClear').addEventListener('click', clearHist);

    let deb;
    input.addEventListener('input', () => {
      syncSearchBox();
      clearTimeout(deb);
      deb = setTimeout(() => {
        state.q = input.value;
        resetRender();
        if (window.scrollY > 300) window.scrollTo({ top: 0 });
      }, 120);
    });
    input.addEventListener('keydown', (ev) => {
      if (ev.key === 'Escape') {
        if (input.value) { input.value = ''; state.q = ''; syncSearchBox(); resetRender(); } else input.blur();
      } else if (ev.key === 'Enter') {
        const first = grid.querySelector('.card');
        if (first && LIST.length === 1) location.href = first.href;
        else input.blur();
      }
    });
    $('.search-clear').addEventListener('click', () => { input.value = ''; state.q = ''; syncSearchBox(); resetRender(); input.focus(); });
    $('#filters').addEventListener('click', (ev) => {
      const b = ev.target.closest('button'); if (!b) return;
      setFilter(b.dataset.f); resetRender();
    });
    $('#sort').addEventListener('click', () => {
      state.sort = state.sort === 'asc' ? 'desc' : 'asc';
      syncSort(); resetRender();
    });
    // 「/」或 ⌘K / Ctrl+K 聚焦搜索
    document.addEventListener('keydown', (ev) => {
      const typing = ev.target.closest && ev.target.closest('input, textarea, [contenteditable]');
      if ((ev.key === '/' && !typing) || ((ev.metaKey || ev.ctrlKey) && ev.key.toLowerCase() === 'k')) {
        ev.preventDefault();
        input.focus();
        input.select();
      }
    });

    resetRender();
    io.observe($('#sentinel'));
    window.addEventListener('hashchange', legacyRedirect);
    if (location.hash === '#search') { input.focus(); history.replaceState(null, '', location.pathname + location.search); }
    // 从单集页返回时刷新进度
    window.addEventListener('pageshow', (ev) => { if (ev.persisted) { loadHist(); updateCounts(); resetRender(); } });
  }

  // 自动加载到 AUTO 期后改为手动「再看 30 期」，让页脚（订阅 / 支持入口）始终够得着
  let AUTO = 90;
  document.addEventListener('click', (e) => {
    if (e.target.closest('[data-more]')) { AUTO = rendered + PAGE; renderMore(); }
  });
  const io = new IntersectionObserver((entries) => {
    if (entries[0].isIntersecting && rendered < LIST.length && rendered < AUTO) renderMore();
  }, { rootMargin: '600px' });



  if (document.getElementById('grid')) init();
})();
