/* GST Desk service worker.
 * The app shell is available after the first successful online visit.
 * API responses are NEVER cached because GST/financial data is sensitive and must stay live.
 */
const VERSION = "gstdesk-v2";
const APP_SHELL = [
  "/",
  "/?source=pwa",
  "/offline",
  "/manifest.webmanifest",
  "/icons/icon-192.png",
  "/icons/icon-512.png",
  "/icons/maskable-512.png",
  "/icons/apple-touch-icon.png",
];

async function cacheShell() {
  const cache = await caches.open(VERSION);
  await Promise.all(APP_SHELL.map(async (url) => {
    try {
      const response = await fetch(url, { cache: "no-store" });
      if (response.ok) await cache.put(url, response.clone());
    } catch (_) {
      // One unavailable shell resource must not prevent the service worker installing.
    }
  }));
}

self.addEventListener("install", (event) => {
  event.waitUntil(cacheShell().then(() => self.skipWaiting()));
});

self.addEventListener("activate", (event) => {
  event.waitUntil(
    caches.keys()
      .then((keys) => Promise.all(keys.filter((key) => key !== VERSION).map((key) => caches.delete(key))))
      .then(() => self.clients.claim())
  );
});

self.addEventListener("fetch", (event) => {
  const request = event.request;
  const url = new URL(request.url);

  if (request.method !== "GET" || url.origin !== self.location.origin) return;
  if (url.pathname.startsWith("/api/")) return; // Never cache live/sensitive API data.

  // Next.js static chunks and public assets: cache-first with network fill.
  if (url.pathname.startsWith("/_next/static/") || url.pathname.startsWith("/icons/") || url.pathname === "/manifest.webmanifest") {
    event.respondWith(
      caches.match(request).then((cached) => {
        if (cached) return cached;
        return fetch(request).then((response) => {
          if (response.ok) {
            const copy = response.clone();
            caches.open(VERSION).then((cache) => cache.put(request, copy));
          }
          return response;
        });
      })
    );
    return;
  }

  // Navigation: network-first, then previously visited page, then the cached
  // dashboard/app shell, and only as a last resort the dedicated offline page.
  if (request.mode === "navigate") {
    event.respondWith(
      fetch(request)
        .then((response) => {
          if (response.ok) {
            const copy = response.clone();
            caches.open(VERSION).then((cache) => cache.put(request, copy));
          }
          return response;
        })
        .catch(async () => {
          const cache = await caches.open(VERSION);
          return (
            (await cache.match(request)) ||
            (await cache.match(new URL(request.url).pathname)) ||
            (await cache.match("/?source=pwa")) ||
            (await cache.match("/")) ||
            (await cache.match("/offline")) ||
            Response.error()
          );
        })
    );
  }
});

self.addEventListener("notificationclick", (event) => {
  event.notification.close();
  event.waitUntil(self.clients.openWindow(event.notification.data?.url || "/"));
});
