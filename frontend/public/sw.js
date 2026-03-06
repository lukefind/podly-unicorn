const CACHE_NAME = 'podly-shell-v1';

const SHELL_ASSETS = [
  '/',
  '/manifest.json',
];

// Backend routes - never cache, always network
const NETWORK_ONLY_PREFIXES = [
  '/api/',
  '/feed',
  '/post/',
  '/trigger',
  '/images/',
  '/rss/',
  '/set_whitelist/',
];

function isNetworkOnly(url) {
  const path = new URL(url).pathname;
  return NETWORK_ONLY_PREFIXES.some((prefix) => path.startsWith(prefix));
}

// Install: cache the app shell
self.addEventListener('install', (event) => {
  event.waitUntil(
    caches.open(CACHE_NAME).then((cache) => cache.addAll(SHELL_ASSETS))
  );
  self.skipWaiting();
});

// Activate: remove old caches and claim clients
self.addEventListener('activate', (event) => {
  event.waitUntil(
    caches.keys().then((keys) =>
      Promise.all(keys.filter((k) => k !== CACHE_NAME).map((k) => caches.delete(k)))
    )
  );
  self.clients.claim();
});

// Fetch: network-only for backend routes, cache-first for static assets
self.addEventListener('fetch', (event) => {
  const { request } = event;

  // Only handle GET requests
  if (request.method !== 'GET') return;

  // Backend routes: always go to network, never cache
  if (isNetworkOnly(request.url)) {
    event.respondWith(fetch(request));
    return;
  }

  // Static assets (/assets/*, /images/logos/*, manifest): cache-first
  event.respondWith(
    caches.match(request).then((cached) => {
      if (cached) return cached;
      return fetch(request).then((response) => {
        if (response.ok) {
          const clone = response.clone();
          caches.open(CACHE_NAME).then((cache) => cache.put(request, clone));
        }
        return response;
      });
    })
  );
});
