import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { BrowserRouter } from "react-router-dom";
// Polices auto-hebergees (audit front 2026-10-14, lot 8) -- avant, chargees
// depuis Google Fonts : dependance reseau externe pour un outil auto-heberge,
// et IP de chaque visiteur transmise a Google. Memes familles, memes
// graisses qu'auparavant ; chaque fichier ne declare que des plages
// unicode, le navigateur ne telecharge que les sous-ensembles utilises.
import "@fontsource/archivo/500.css";
import "@fontsource/archivo/600.css";
import "@fontsource/archivo/700.css";
import "@fontsource/public-sans/400.css";
import "@fontsource/public-sans/500.css";
import "@fontsource/public-sans/600.css";
import "@fontsource/ibm-plex-mono/400.css";
import "@fontsource/ibm-plex-mono/500.css";
import "@fontsource/ibm-plex-mono/600.css";
import "./index.css";
import App from "./App.tsx";

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <BrowserRouter>
      <App />
    </BrowserRouter>
  </StrictMode>,
);
