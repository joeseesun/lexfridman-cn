/* Lex Fridman 播客全访谈 · Service Worker
   - 静态资源（样式 / 脚本 / 图标 / 字体）：先用缓存，后台更新
   - 页面与数据：网络优先，断网时回退到缓存；读过的文章因此可以离线阅读
   - 都没有时显示离线页 */
const VERSION = 'lex-v1';
const SHELL = `${VERSION}-shell`;
const PAGES = `${VERSION}-pages`;
const ASSETS = `${VERSION}-assets`;
const PRECACHE = ['/', '/offline.html', '/style.css', '/app.js', '/ep.js', '/icon.svg', '/favicon.ico', '/site.webmanifest', '/data/episodes.json'];
const MAX_PAGES = 80;
const MAX_ASSETS = 400;

self.addEventListener('install', (e) => {
  e.waitUntil(caches.open(SHELL).then((c) => c.addAll(PRECACHE)).then(() => self.skipWaiting()));
});

self.addEventListener('activate', (e) => {
  e.waitUntil(
    caches.keys()
      .then((keys) => Promise.all(keys.filter((k) => !k.startsWith(VERSION)).map((k) => caches.delete(k))))
      .then(() => self.clients.claim())
  );
});

async function trim(name, max) {
  const c = await caches.open(name);
  const keys = await c.keys();
  for (let i = 0; i < keys.length - max; i++) await c.delete(keys[i]);
}

async function networkFirst(req) {
  const c = await caches.open(PAGES);
  try {
    const res = await fetch(req);
    if (res.ok) { c.put(req, res.clone()); trim(PAGES, MAX_PAGES); }
    return res;
  } catch (err) {
    const hit = (await c.match(req, { ignoreSearch: req.mode === 'navigate' })) || (await caches.match(req, { ignoreSearch: true }));
    if (hit) return hit;
    if (req.mode === 'navigate') return caches.match('/offline.html');
    throw err;
  }
}

async function staleWhileRevalidate(req) {
  const c = await caches.open(ASSETS);
  // 精确匹配（带 ?v= 版本号），发版后新样式立即生效；断网时再退回任意版本
  const hit = await c.match(req);
  const fresh = fetch(req).then((res) => {
    if (res && (res.ok || res.type === 'opaque')) { c.put(req, res.clone()); trim(ASSETS, MAX_ASSETS); }
    return res;
  }).catch(() => hit || caches.match(req, { ignoreSearch: true }));
  return hit || fresh;
}

self.addEventListener('fetch', (e) => {
  const req = e.request;
  if (req.method !== 'GET') return;
  const url = new URL(req.url);
  // 音频走浏览器自身的范围请求，不经 SW；统计脚本也不缓存
  if (/\.(mp3|m4a)$/i.test(url.pathname) || url.hostname.startsWith('umami.')) return;
  const sameOrigin = url.origin === self.location.origin;
  if (req.mode === 'navigate' || (sameOrigin && /\.(json|md|xml|txt)$/.test(url.pathname))) {
    e.respondWith(networkFirst(req));
    return;
  }
  const isAsset = (sameOrigin && /\.(css|js|svg|png|jpg|ico|webmanifest)$/.test(url.pathname)) ||
    /^(fonts\.googleapis\.cn|fonts\.gstatic\.cn|i\.ytimg\.com|cdn\.jsdelivr\.net)$/.test(url.hostname);
  if (isAsset) e.respondWith(staleWhileRevalidate(req));
});
