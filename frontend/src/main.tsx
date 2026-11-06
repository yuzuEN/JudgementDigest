import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { BrowserRouter } from "react-router-dom";
import App from "./App";
import { IntakeProvider } from "./state";
import "./styles.css";
import { applyTheme, initialTheme } from "./theme";

applyTheme(initialTheme());

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <BrowserRouter>
      <IntakeProvider>
        <App />
      </IntakeProvider>
    </BrowserRouter>
  </StrictMode>,
);
