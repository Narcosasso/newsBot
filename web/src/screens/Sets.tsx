import { useEffect, useMemo, useState } from "preact/hooks";
import { api, type SeriesGroup, type SetDetail } from "../api";
import { date, plural, price } from "../format";
import { go } from "../nav";
import { CardGrid, Header, Icon, Spinner } from "../ui";

const LANGS = [
  { id: "en", label: "🇬🇧 Internazionali" },
  { id: "ja", label: "🇯🇵 Giapponesi" },
  { id: "zh", label: "🇨🇳 Cinesi" },
];
let lastLang = "en";
let lastOnlyMine = false;

export function SetsScreen({ route }: { route: string[] }) {
  // #/sets  oppure  #/sets/en/sv03.5
  return route.length >= 3 ? <SetView lang={route[1]} id={route.slice(2).join("/")} /> : <SetList />;
}

function SetList() {
  const [lang, setLang] = useState(lastLang);
  const [data, setData] = useState<SeriesGroup[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [q, setQ] = useState("");
  const [onlyMine, setOnlyMine] = useState(lastOnlyMine);

  useEffect(() => {
    lastLang = lang;
    setData(null);
    setError(null);
    api.sets(lang).then((r) => setData(r.series)).catch((e) => setError((e as Error).message));
  }, [lang]);
  useEffect(() => { lastOnlyMine = onlyMine; }, [onlyMine]);

  const groups = useMemo(() => {
    const needle = q.trim().toLowerCase();
    return (data ?? []).map((g) => ({
      ...g,
      sets: g.sets.filter((s) => (!onlyMine || s.owned > 0)
        && (!needle || `${s.name} ${s.id}`.toLowerCase().includes(needle))),
    })).filter((g) => g.sets.length);
  }, [data, q, onlyMine]);

  return (
    <>
      <Header title="Espansioni" />
      <div class="searchbar">
        <Icon name="search" size={20} />
        <input type="search" placeholder="Cerca un set" value={q} onInput={(e) => setQ((e.target as HTMLInputElement).value)} />
      </div>
      <div class="chips">
        {LANGS.map((l) => <button class={`chip ${lang === l.id ? "on" : ""}`} onClick={() => setLang(l.id)}>{l.label}</button>)}
        <span class="chip-sep" />
        <button class={`chip ${onlyMine ? "on" : ""}`} onClick={() => setOnlyMine(!onlyMine)}>Solo i miei</button>
      </div>
      {error && <p class="error pad">{error}</p>}
      {!data && !error && <Spinner label="Carico le espansioni…" />}
      {data && groups.length === 0 && <p class="muted pad">Nessun set con questi filtri.</p>}
      {groups.map((g) => (
        <section>
          <h2 class="section">{g.name}</h2>
          <div class="list">
            {g.sets.map((s) => {
              const total = s.total || s.official || 0;
              const pctOwned = total ? Math.min(100, Math.round((s.owned / total) * 100)) : 0;
              return (
                <button class="set-item" onClick={() => go(`sets/${lang}/${encodeURIComponent(s.id)}`)}>
                  <div class="set-logo-box">
                    {s.logo || s.symbol
                      ? <img src={(s.logo || s.symbol)!} alt="" loading="lazy" onError={(e) => ((e.target as HTMLImageElement).style.visibility = "hidden")} />
                      : <Icon name="grid" size={22} />}
                  </div>
                  <div class="set-main">
                    <div class="strong">{s.name}</div>
                    <div class="muted small">{s.id} · {plural(total, "carta", "carte")}</div>
                    {s.owned > 0 && (
                      <div class="progress"><div style={{ width: `${pctOwned}%` }} /></div>
                    )}
                  </div>
                  <div class="set-count">
                    {s.owned > 0 ? <><b>{s.owned}</b><span>/{total}</span></> : <span class="muted">—</span>}
                  </div>
                </button>
              );
            })}
          </div>
        </section>
      ))}
    </>
  );
}

const FILTERS = [
  { id: "all", label: "Tutte" },
  { id: "owned", label: "Le mie" },
  { id: "missing", label: "Mancanti" },
];

function SetView({ lang, id }: { lang: string; id: string }) {
  const [data, setData] = useState<SetDetail | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [filter, setFilter] = useState("all");

  useEffect(() => {
    setData(null);
    api.set(lang, id).then(setData).catch((e) => setError((e as Error).message));
  }, [lang, id]);

  if (error) return <><Header title="Espansione" /><p class="error pad">{error}</p></>;
  if (!data) return <Spinner label="Carico il set…" />;

  const cards = data.cards.filter((c) => filter === "all" || (filter === "owned" ? c.owned : !c.owned));
  const pctOwned = data.total ? Math.round((data.owned_unique / data.total) * 100) : 0;
  return (
    <>
      <div class="screen-head">
        <button class="round" onClick={() => go("sets")} aria-label="Indietro"><Icon name="back" /></button>
      </div>
      <section class="set-hero">
        {data.logo && <img class="set-hero-logo" src={data.logo} alt="" onError={(e) => ((e.target as HTMLImageElement).style.display = "none")} />}
        <h1>{data.name}</h1>
        <div class="muted">{[data.serie, data.code, data.release_date ? `uscita ${date(data.release_date)}` : null].filter(Boolean).join(" · ")}</div>
        <div class="set-progress">
          <div class="progress big"><div style={{ width: `${pctOwned}%` }} /></div>
          <div class="row gap small">
            <b>{data.owned_unique}/{data.total} carte ({pctOwned}%)</b>
            {data.owned_cards > data.owned_unique && <span class="muted">{data.owned_cards} copie</span>}
            {data.owned_value > 0 && <span class="muted">valore {price(data.owned_value)}</span>}
          </div>
        </div>
      </section>
      <div class="chips">
        {FILTERS.map((f) => <button class={`chip ${filter === f.id ? "on" : ""}`} onClick={() => setFilter(f.id)}>{f.label}</button>)}
      </div>
      {cards.length === 0 && <p class="muted pad">{filter === "owned" ? "Non hai ancora carte di questo set." : "Hai tutte le carte del set!"}</p>}
      <CardGrid cards={cards} dimMissing={data.owned_unique > 0} hideSet />
    </>
  );
}
