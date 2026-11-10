/* Mini service worker: makes the app installable and quick to open.
 * It caches ONLY Mini's own static files. API calls, sign-in, Supabase,
 * live voice and anything cross-origin always go straight to the network
 * and are never stored. */
const CACHE = 'mini-shell-v1';
const SHELL = ['/', '/manifest.webmanifest', '/icons/mini-192.png', '/icons/mini-512.png',
  '/mini-capture.worklet.js', '/mini-playback.worklet.js'];

self.addEventListener('install', (event) => {
  event.waitUntil(caches.open(CACHE).then((c) => c.addAll(SHELL)).then(() => self.skipWaiting()));
});

self.addEventListener('activate', (event) => {
  event.waitUntil(caches.keys()
    .then((keys) => Promise.all(keys.filter((k) => k !== CACHE).map((k) => caches.delete(k))))
    .then(() => self.clients.claim()));
});

self.addEventListener('fetch', (event) => {
  const req = event.request;
  const url = new URL(req.url);
  if (req.method !== 'GET' || url.origin !== self.location.origin || url.pathname.startsWith('/api/')) return;
  if (req.mode === 'navigate') {
    // Fresh app when online; the cached shell when offline. OAuth redirects
    // (?code=...) always go to the network.
    event.respondWith(fetch(req).then((res) => {
      if (res.ok && !url.search) caches.open(CACHE).then((c) => c.put('/', res.clone()));
      return res;
    }).catch(() => caches.match('/')));
    return;
  }
  if (url.pathname.startsWith('/assets/') || url.pathname.startsWith('/icons/')) {
    // Vite file names are content-hashed, so cache-first is safe.
    event.respondWith(caches.match(req).then((hit) => hit || fetch(req).then((res) => {
      if (res.ok) { const copy = res.clone(); caches.open(CACHE).then((c) => c.put(req, copy)); }
      return res;
    })));
  }
});
