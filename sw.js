// Kanban Board — Cache-first service worker
const CACHE = "kanban-v1";

self.addEventListener("install", (event) => {
  self.skipWaiting();
  event.waitUntil(
    caches.open(CACHE).then((cache) =>
      cache.addAll(["/", "/manifest.json", "/sw.js"])
    )
  );
});

self.addEventListener("activate", (event) => {
  event.waitUntil(
    caches.keys().then((keys) =>
      Promise.all(keys.filter((k) => k !== CACHE).map((k) => caches.delete(k)))
    )
  );
});

self.addEventListener("fetch", (event) => {
  event.respondWith(
    caches.open(CACHE).then((cache) =>
      cache.match(event.request).then((cached) => {
        const fetchPromise = fetch(event.request).then((network) => {
          if (network.ok && event.request.method === "GET") {
            cache.put(event.request, network.clone());
          }
          return network;
        }).catch(() => cached);
        return cached || fetchPromise;
      })
    )
  );
});
