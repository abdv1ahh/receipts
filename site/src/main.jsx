import { StrictMode } from "react";
import { createRoot } from "react-dom/client";

// Self-hosted, so first paint never waits on a third-party font host and no visitor's IP reaches
// one. Instrument Serif ships a single weight — that is the point of choosing it; it is the display
// face and it appears at section heads and nowhere else.
import "@fontsource/instrument-serif/400.css";
import "@fontsource-variable/inter";
import "@fontsource/ibm-plex-mono/400.css";
import "@fontsource/ibm-plex-mono/600.css";

import "./styles.css";
import { App } from "./App.jsx";

createRoot(document.getElementById("root")).render(
  <StrictMode>
    <App />
  </StrictMode>,
);
