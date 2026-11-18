import { useEffect, useState } from "preact/hooks";
import { api, AuthError } from "./api";
import { CardDetailScreen } from "./screens/CardDetail";
import { LoginScreen } from "./screens/Login";
import { ScanScreen } from "./screens/Scan";
import { SearchScreen } from "./screens/Search";
import { PokedexScreen } from "./screens/Pokedex";
import { SetsScreen } from "./screens/Sets";
import { CollectionScreen } from "./screens/Collection";
import { go } from "./nav";
import { Icon } from "./ui";

export type Tab = "dex" | "sets" | "collection" | "scan" | "search";

const TABS: { id: Tab; label: string; icon: string }[] = [
  { id: "dex", label: "Pokédex", icon: "dex" },
  { id: "sets", label: "Espansioni", icon: "grid" },
  { id: "collection", label: "Collezione", icon: "folder" },
  { id: "scan", label: "Scansiona", icon: "scan" },
  { id: "search", label: "Cerca", icon: "search" },
];

/** Percorso dall'hash: "#/card/en/sv03.5-006" -> ["card", "en", "sv03.5-006"]. */
function useRoute(): string[] {
  const read = () => decodeURIComponent(location.hash.replace(/^#\/?/, "")).split("/").filter(Boolean);
  const [route, setRoute] = useState(read);
  useEffect(() => {
    const on = () => setRoute(read());
    window.addEventListener("hashchange", on);
    return () => window.removeEventListener("hashchange", on);
  }, []);
  return route;
}

export function App() {
  const route = useRoute();
  const [state, setState] = useState<"loading" | "login" | "ready">("loading");
  const [lastTab, setLastTab] = useState<Tab>("search");
  const [lastPath, setLastPath] = useState("search");  // chiudendo una carta si torna esattamente qui

  const check = () =>
    api
      .me()
      .then(() => setState("ready"))
      .catch((e) => setState(e instanceof AuthError ? "login" : "ready"));

  useEffect(() => {
    check();
    // Qualsiasi chiamata che scopre la sessione scaduta riporta al PIN.
    const onAuth = (e: PromiseRejectionEvent) => {
      if (e.reason instanceof AuthError) setState("login");
    };
    window.addEventListener("unhandledrejection", onAuth);
    return () => window.removeEventListener("unhandledrejection", onAuth);
  }, []);

  const head = route[0] || "search";
  const isCard = head === "card" && route.length >= 3;
  const tab: Tab = (TABS.find((t) => t.id === head)?.id ?? lastTab) as Tab;
  useEffect(() => {
    if (!isCard && TABS.some((t) => t.id === head)) {
      setLastTab(head as Tab);
      setLastPath(route.map(encodeURIComponent).join("/"));
    }
  }, [route.join("/"), isCard]);

  if (state === "loading") return <div class="splash"><Icon name="vault" size={64} /></div>;
  if (state === "login") return <LoginScreen onDone={() => setState("ready")} />;

  return (
    <div class="app">
      <main class="screen" hidden={isCard}>
        {tab === "search" && <SearchScreen />}
        {tab === "scan" && <ScanScreen />}
        {tab === "collection" && <CollectionScreen />}
        {tab === "sets" && <SetsScreen route={head === "sets" ? route : ["sets"]} />}
        {tab === "dex" && <PokedexScreen />}
      </main>
      {isCard && <CardDetailScreen lang={route[1]} id={route.slice(2).join("/")} onClose={() => go(lastPath)} />}
      <nav class="tabbar" hidden={isCard}>
        {TABS.map((t) => (
          <button class={`tab ${t.id === tab ? "active" : ""}`} onClick={() => go(t.id)} aria-label={t.label}>
            <Icon name={t.icon} size={24} />
            <span>{t.label}</span>
          </button>
        ))}
      </nav>
    </div>
  );
}
