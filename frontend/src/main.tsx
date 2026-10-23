import React from "react";
import ReactDOM from "react-dom/client";
import "@fontsource-variable/inter";
import "./styles.css";
import App from "./App";
import { USE_MOCKS } from "./env";

async function start() {
  if (USE_MOCKS) {
    const { worker } = await import("./mocks/browser");
    // запросы, которых нет в моках (HMR, шрифты, ассеты), идут как обычно
    await worker.start({ onUnhandledRequest: "bypass", quiet: true });
  } else if ("serviceWorker" in navigator) {
    // после `npm run dev:mock` в браузере остаётся воркер MSW — снимаем, чтобы он не перехватывал реальный API
    const regs = await navigator.serviceWorker.getRegistrations();
    await Promise.all(regs.filter((r) => r.active?.scriptURL.endsWith("/mockServiceWorker.js")).map((r) => r.unregister()));
  }
  ReactDOM.createRoot(document.getElementById("root")!).render(
    <React.StrictMode>
      <App />
    </React.StrictMode>,
  );
}

start();
