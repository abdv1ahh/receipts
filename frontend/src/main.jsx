import React from "react";
import { createRoot } from "react-dom/client";
import App from "./App.jsx";

// The identity faces, self-hosted. The marketing site has carried these since Phase 7 and the app
// did not, so a visitor arriving from the pitch at a record page saw the same product in a
// different typeface. Self-hosted rather than fetched: the CSP is `default-src 'self'`, so a font
// host would be blocked outright, and no reader's address should reach one anyway.
//
// Instrument Serif ships a single weight, which is the point of choosing it. Only the weights
// actually used are imported.
import "@fontsource/instrument-serif/400.css";
import "@fontsource-variable/inter";
import "@fontsource/ibm-plex-mono/400.css";
import "@fontsource/ibm-plex-mono/600.css";

import "./styles.css";

createRoot(document.getElementById("root")).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>
);
