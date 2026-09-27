import { StrictMode } from "react";
import { createRoot } from "react-dom/client";

import { App } from "./App";
import { takeTokenFromUrl } from "./api";
import "./styles.css";

const token = takeTokenFromUrl(window.location, window.history);

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <App token={token} />
  </StrictMode>,
);
