/*
 * Service worker do painel.
 *
 * Faz duas coisas, as duas pelo mesmo motivo — o painel é consultado no
 * celular, muitas vezes em rede ruim:
 *
 * 1. Guarda a casca da aplicação (HTML, JS, CSS) para abrir mesmo sem rede,
 *    mostrando os dados que já estavam carregados em vez de uma página de
 *    erro do navegador. Nunca guarda resposta de /api: dado de monitoramento
 *    velho apresentado como atual seria pior que dado nenhum.
 *
 * 2. Recebe as notificações do servidor (Web Push) e as mostra como aviso do
 *    sistema, com o painel fechado.
 */
const CACHE = "anomalydetect-v1";
const APP_SHELL = ["/", "/index.html", "/manifest.webmanifest", "/icon.svg"];

self.addEventListener("install", (event) => {
  event.waitUntil(
    caches.open(CACHE).then((cache) => cache.addAll(APP_SHELL)).then(() => self.skipWaiting())
  );
});

self.addEventListener("activate", (event) => {
  event.waitUntil(
    caches
      .keys()
      .then((nomes) => Promise.all(nomes.filter((n) => n !== CACHE).map((n) => caches.delete(n))))
      .then(() => self.clients.claim())
  );
});

self.addEventListener("fetch", (event) => {
  const { request } = event;
  const url = new URL(request.url);
  // Só GET da própria origem entra no cache. API e WebSocket passam direto:
  // é sempre a rede que manda em dado de monitoramento.
  if (request.method !== "GET" || url.origin !== self.location.origin) return;
  if (url.pathname.startsWith("/api") || url.pathname.startsWith("/ws")) return;

  if (request.mode === "navigate") {
    // Rede primeiro: a casca em cache é o plano B, não o padrão.
    event.respondWith(fetch(request).catch(() => caches.match("/index.html")));
    return;
  }
  event.respondWith(
    caches.match(request).then(
      (cacheada) =>
        cacheada ||
        fetch(request).then((resposta) => {
          if (resposta.ok && resposta.type === "basic") {
            const copia = resposta.clone();
            caches.open(CACHE).then((cache) => cache.put(request, copia));
          }
          return resposta;
        })
    )
  );
});

self.addEventListener("push", (event) => {
  let dados = {};
  try {
    dados = event.data ? event.data.json() : {};
  } catch (e) {
    dados = { title: "AnomalyDetect", body: event.data ? event.data.text() : "" };
  }
  event.waitUntil(
    self.registration.showNotification(dados.title || "AnomalyDetect", {
      body: dados.body || "",
      icon: "/icon.svg",
      badge: "/icon-maskable.svg",
      // A mesma tag substitui o aviso anterior em vez de empilhar dez avisos
      // do mesmo problema na tela de bloqueio.
      tag: dados.tag || "anomalydetect",
      data: { link: dados.link || "/" },
    })
  );
});

self.addEventListener("notificationclick", (event) => {
  event.notification.close();
  const destino = (event.notification.data && event.notification.data.link) || "/";
  event.waitUntil(
    self.clients.matchAll({ type: "window", includeUncontrolled: true }).then((janelas) => {
      for (const janela of janelas) {
        if ("focus" in janela) {
          janela.navigate(destino);
          return janela.focus();
        }
      }
      return self.clients.openWindow(destino);
    })
  );
});
