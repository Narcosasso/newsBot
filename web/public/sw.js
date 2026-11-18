// Service worker di PokeVault: apre l'app subito anche con rete lenta.
// - pagine: prima la rete (così ricevi sempre l'ultima versione), la copia salvata solo se sei offline
// - file /assets/ (hanno l'impronta nel nome, non cambiano mai): dalla cache
// - /api e immagini esterne: mai in cache qui (i prezzi devono essere freschi)
const CACHE = "pokevault-v1";

self.addEventListener("install", (event) => {
  event.waitUntil(caches.open(CACHE).then((c) => c.addAll(["/", "/manifest.webmanifest"])));
  self.skipWaiting();
});

self.addEventListener("activate", (event) => {
  event.waitUntil(
    caches.keys().then((keys) => Promise.all(keys.filter((k) => k !== CACHE).map((k) => caches.delete(k)))),
  );
  self.clients.claim();
});

self.addEventListener("fetch", (event) => {
  const url = new URL(event.request.url);
  if (event.request.method !== "GET" || url.origin !== self.location.origin || url.pathname.startsWith("/api/")) {
    return;
  }
  if (url.pathname.startsWith("/assets/")) {
    event.respondWith(
      caches.match(event.request).then(
        (hit) =>
          hit ||
          fetch(event.request).then((resp) => {
            const copy = resp.clone();
            caches.open(CACHE).then((c) => c.put(event.request, copy));
            return resp;
          }),
      ),
    );
    return;
  }
  if (event.request.mode === "navigate") {
    event.respondWith(
      fetch(event.request)
        .then((resp) => {
          const copy = resp.clone();
          caches.open(CACHE).then((c) => c.put("/", copy));
          return resp;
        })
        .catch(() => caches.match("/")),
    );
  }
});
