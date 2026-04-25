const CACHE_NAME = 'univote-v1';
const ASSETS = [
  '/',
  '/login',
  '/register',
  '/static/style.css',
  '/static/script.js',
  '/static/univote_logo.jpg',
  '/static/icon-192.png'
];

self.addEventListener('install', (e) => {
  e.waitUntil(caches.open(CACHE_NAME).then(cache => cache.addAll(ASSETS)));
});

self.addEventListener('fetch', (e) => {
  // Network first, fallback to cache for offline support
  e.respondWith(
    fetch(e.request).catch(() => caches.match(e.request) || caches.match('/'))
  );
});