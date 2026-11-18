import { render } from "preact";
import { App } from "./app";
import "./styles.css";

render(<App />, document.getElementById("app")!);

if ("serviceWorker" in navigator) {
  window.addEventListener("load", () => {
    navigator.serviceWorker.register("/sw.js").catch(() => {
      /* senza service worker l'app funziona lo stesso */
    });
  });
}
