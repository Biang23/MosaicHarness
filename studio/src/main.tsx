import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { FoundryApp } from "./app";
import "./styles.css";

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <FoundryApp />
  </StrictMode>,
);
