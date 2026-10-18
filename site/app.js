/* Lex Fridman 播客全访谈 · 首页列表 */
(function () {
  'use strict';
  const $ = (s) => document.querySelector(s);
  let DATA = [];
  let state = { q: '', f: 'all' };
  let rendered = 0;
  const PAGE = 30;

  /* 返回顶部 */
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

  /* 旧 hash 链接（#/slug）301 式跳转到真实单集页 */
  function legacyRedirect() {
    const m = location.hash.match(/^#\/([^/]+)$/);
    if (m) location.replace('/ep/' + m[1] + '/');
  }

  function cardHTML(e) {
    const thumb = e.y
      ? `<img loading="lazy" src="https://i.ytimg.com/vi/${e.y}/mqdefault.jpg" alt="${esc(e.zh || e.t)}">`
      : '<div class="no-img">LEX</div>';
    const num = e.n != null ? `#${e.n}` : '特辑';
    const date = e.d ? e.d.slice(0, 7).replace('-', '.') : '';
    const badges = [];
    if (e.zh) badges.push('<span class="badge zh">中文精读</span>');
    if (e.tr) badges.push(`<span class="badge" title="${e.tr === 'asr' ? '机器转写文稿' : '英文文稿'}">文稿</span>`);
    const zhTitle = e.zh || e.t;
    const enTitle = e.zh ? `<div class="card-title-en">${esc(e.t)}</div>` : '';
    return `<a class="card" href="/ep/${e.s}/">
      <div class="thumb">${thumb}<span class="num">${num}</span></div>
      <div class="card-body">
        <div class="card-title">${esc(zhTitle)}</div>
        ${enTitle}
        <div class="card-meta">
          <span class="badges">${badges.join('')}</span>
          <span>${date}</span>
        </div>
      </div>
    </a>`;
  }

  function esc(s) {
    return (s || '').replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
  }

  function filtered() {
    const q = state.q.trim().toLowerCase();
    return DATA.filter((e) => {
      if (state.f === 'zh' && !e.zh) return false;
      if (state.f === 'tr' && !e.tr) return false;
      if (q) {
        const hay = (e.t + ' ' + (e.zh || '') + ' ' + (e.guest || '') + ' ' + e.s + ' ' + (e.n != null ? '#' + e.n : '')).toLowerCase();
        if (!hay.includes(q)) return false;
      }
      return true;
    });
  }

  function resetRender() {
    rendered = 0;
    $('#grid').innerHTML = '';
    renderMore();
  }

  function renderMore() {
    const list = filtered();
    const slice = list.slice(rendered, rendered + PAGE);
    if (slice.length) {
      $('#grid').insertAdjacentHTML('beforeend', slice.map(cardHTML).join(''));
      rendered += slice.length;
    }
    $('#sentinel').textContent = rendered >= list.length
      ? `共 ${list.length} 期${state.q || state.f !== 'all' ? '（筛选结果）' : ''}`
      : '加载中…';
  }

  const io = new IntersectionObserver((entries) => {
    if (entries[0].isIntersecting && rendered < filtered().length) renderMore();
  }, { rootMargin: '600px' });

  async function init() {
    const res = await fetch('data/episodes.json');
    DATA = (await res.json()).episodes;

    const nTr = DATA.filter((e) => e.tr).length;
    const nZh = DATA.filter((e) => e.zh).length;
    $('#stats').innerHTML = `共 <b>${DATA.length}</b> 期 · 文稿 <b>${nTr}</b> 期 · 中文精读 <b>${nZh}</b> 期`;

    $('#search').addEventListener('input', (ev) => { state.q = ev.target.value; resetRender(); });
    $('#filters').addEventListener('click', (ev) => {
      const b = ev.target.closest('button'); if (!b) return;
      document.querySelectorAll('#filters button').forEach((x) => x.classList.remove('on'));
      b.classList.add('on');
      state.f = b.dataset.f; resetRender();
    });
    document.addEventListener('keydown', (ev) => {
      if (ev.key === 'Escape') {
        $('#rewardModal').hidden = true; $('#followModal').hidden = true;
      }
    });
    bindModal('#rewardBtn', '#rewardModal');
    bindModal('#followBtn', '#followModal');

    legacyRedirect();
    resetRender();
    io.observe($('#sentinel'));
    window.addEventListener('hashchange', legacyRedirect);
  }

  function bindModal(btnId, modalId) {
    const modal = $(modalId);
    $(btnId).addEventListener('click', () => { modal.hidden = false; });
    modal.querySelector('.modal-close').addEventListener('click', () => { modal.hidden = true; });
    modal.addEventListener('click', (ev) => { if (ev.target === modal) modal.hidden = true; });
  }

  /* 复制 RSS 订阅地址（页脚） */
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

  init();
})();
