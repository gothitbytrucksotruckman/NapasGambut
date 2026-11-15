// Offline Service Worker: network-first for same-origin app assets and bundle/* files, cached copy when offline.
// v2 drops caches filled by the old cache-first worker, which could pin a stale bundle.
const CACHE_NAME = 'napas-gambut-v2';

self.addEventListener('install', () => {
  self.skipWaiting();
});

self.addEventListener('activate', (event) => {
  event.waitUntil(
    caches.keys().then((keys) =>
      Promise.all(keys.filter((k) => k !== CACHE_NAME).map((k) => caches.delete(k))),
    ).then(() => self.clients.claim()),
  );
});

self.addEventListener('fetch', (event) => {
  const req = event.request;
  if (req.method !== 'GET') return;

  const url = new URL(req.url);
  // Ignore external basemap tiles and cross-origin requests.
  if (url.origin !== self.location.origin) return;

  // Network first: a redeployed bundle (mock -> real) must reach returning visitors; the cache is only the offline copy.
  event.respondWith(
    caches.open(CACHE_NAME).then(async (cache) => {
      try {
        const res = await fetch(req);
        if (res && res.status === 200) {
          cache.put(req, res.clone());
        }
        return res;
      } catch (err) {
        const cached = await cache.match(req);
        if (cached) return cached;
        throw err;
      }
    }),
  );
});
