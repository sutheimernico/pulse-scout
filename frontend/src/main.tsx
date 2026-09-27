import { StrictMode } from "react";
import { createRoot } from "react-dom/client";

import { App } from "./App";
import { takeTokenFromUrl } from "./api";
import "./styles.css";

const token = takeTokenFromUrl(window.location, window.history);

// Production only: in `npm run dev` a worker would serve stale bundles over the live reload.
// A module worker, so it can import its pure strategy file (public/sw-strategy.js).
if (import.meta.env.PROD && "serviceWorker" in navigator) {
  window.addEventListener("load", () => {
    navigator.serviceWorker.register("/sw.js", { type: "module", scope: "/" }).catch(() => {});
  });
}

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <App token={token} />
  </StrictMode>,
);
