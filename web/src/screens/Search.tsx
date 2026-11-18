import { useEffect, useRef, useState } from "preact/hooks";
import { api, type CardSummary } from "../api";
import { go } from "../nav";
import { CardGrid, Header, Icon, Spinner } from "../ui";

const FILTERS = [
  { id: "all", label: "Tutte" },
  { id: "en", label: "🇬🇧 Internazionali" },
  { id: "ja", label: "🇯🇵 Giapponesi" },
];

// La ricerca resta quando torni indietro da una carta.
let lastQuery = "";
let lastLang = "all";

/** Apre la scheda Cerca con un testo già scritto (es. dall'illustratore o dal set di una carta). */
export function searchFor(q: string) {
  lastQuery = q;
  window.dispatchEvent(new CustomEvent("pv:search", { detail: q }));
  go("search");
}

export function SearchScreen() {
  const [q, setQ] = useState(lastQuery);
  const [lang, setLang] = useState(lastLang);
  const [results, setResults] = useState<CardSummary[] | null>(null);
  const [recent, setRecent] = useState<CardSummary[]>([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const seq = useRef(0);

  useEffect(() => {
    const loadRecent = () => api.recent().then((r) => setRecent(r.cards)).catch(() => {});
    loadRecent();
    const onSearch = (e: Event) => setQ((e as CustomEvent<string>).detail);
    // Tornando su Cerca da una carta, i "visti di recente" si aggiornano.
    const onHash = () => location.hash.startsWith("#/search") && loadRecent();
    window.addEventListener("pv:search", onSearch);
    window.addEventListener("hashchange", onHash);
    return () => {
      window.removeEventListener("pv:search", onSearch);
      window.removeEventListener("hashchange", onHash);
    };
  }, []);

  useEffect(() => {
    lastQuery = q;
    lastLang = lang;
    const term = q.trim();
    if (term.length < 2) {
      setResults(null);
      return;
    }
    const id = ++seq.current;
    const timer = setTimeout(async () => {
      setBusy(true);
      setError(null);
      try {
        const r = await api.search(term, lang);
        if (id === seq.current) setResults(r.cards);
      } catch (e) {
        if (id === seq.current) setError((e as Error).message);
      } finally {
        if (id === seq.current) setBusy(false);
      }
    }, 350);
    return () => clearTimeout(timer);
  }, [q, lang]);

  return (
    <>
      <Header title="Cerca" />
      <div class="searchbar">
        <Icon name="search" size={20} />
        <input type="search" placeholder="Nome, #Pokédex, illustratore o set:151" value={q}
          onInput={(e) => setQ((e.target as HTMLInputElement).value)} autoCapitalize="off" autoCorrect="off"
          spellcheck={false} enterKeyHint="search" />
        {q && <button class="clear" onClick={() => setQ("")} aria-label="Cancella"><Icon name="close" size={16} /></button>}
      </div>
      <div class="chips">
        {FILTERS.map((f) => (
          <button class={`chip ${lang === f.id ? "on" : ""}`} onClick={() => setLang(f.id)}>{f.label}</button>
        ))}
      </div>

      {busy && <Spinner />}
      {error && <p class="error pad">{error}</p>}
      {!busy && results !== null && results.length === 0 && (
        <div class="empty small">
          <p>Nessuna carta trovata per «{q.trim()}».</p>
          <p class="muted">Prova con il nome inglese, il numero (es. <b>30C 154</b>) o <b>set:</b> e il codice.</p>
        </div>
      )}
      {!busy && results && results.length > 0 && <CardGrid cards={results} />}

      {results === null && (
        <>
          <div class="empty small">
            <Icon name="search" size={40} />
            <h2>Cerca carte ed espansioni</h2>
            <p class="muted">Prova <b>Gengar ex</b>, <b>#0094</b>, <b>Arita</b>, <b>set:151</b> o <b>30C 154</b>.</p>
          </div>
          {recent.length > 0 && (
            <>
              <h2 class="section">Visti di recente</h2>
              <CardGrid cards={recent} />
            </>
          )}
        </>
      )}
    </>
  );
}
