import React from "react";
import ReactDOM from "react-dom/client";
import App from "./App";
import "./index.css";
import { applyDisplay } from "./lib/display";
import { getLocale } from "./lib/i18n";

// Antes da primeira pintura: densidade, tamanho da letra e idioma escolhidos
// entram como atributo do documento, sem piscar o padrão antes.
applyDisplay();
document.documentElement.lang = getLocale();

ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>
);

// Service worker: casca offline e recebimento das notificações no celular.
// Registrado depois do load para não disputar banda com a primeira pintura, e
// só em produção — em desenvolvimento ele serviria arquivos antigos do cache.
if ("serviceWorker" in navigator && import.meta.env.PROD) {
  window.addEventListener("load", () => {
    navigator.serviceWorker.register("/sw.js").catch((erro) => {
      console.warn("Service worker não registrado:", erro);
    });
  });
}
