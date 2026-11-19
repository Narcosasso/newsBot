import { useEffect, useMemo, useState } from "preact/hooks";
import { api, type CardSummary, type SeriesGroup, type SetBrief, type SetDetail } from "../api";
import { date, plural, price } from "../format";
import { go } from "../nav";
import { CardGrid, Header, Icon, SetLogo, SortBar, type SortOption, Spinner, sortBy } from "../ui";

const LANGS = [
  { id: "en", label: "🇬🇧 Internazionali" },
  { id: "ja", label: "🇯🇵 Giapponesi" },
  { id: "zh", label: "🇨🇳 Cinesi" },
];
const LIST_SORTS: SortOption[] = [
  { id: "release", label: "Uscita (per serie)", desc: true },
  { id: "name", label: "Nome" },
  { id: "progress", label: "Completamento", desc: true },
  { id: "owned", label: "Carte che ho", desc: true },
  { id: "size", label: "Numero di carte", desc: true },
];
const CARD_SORTS: SortOption[] = [
  { id: "number", label: "Numero" },
  { id: "name", label: "Nome" },
  { id: "owned", label: "Prima quelle che ho", desc: true },
];
const FILTERS = [
  { id: "all", label: "Tutte" },
  { id: "owned", label: "Le mie" },
  { id: "missing", label: "Mancanti" },
];
// Scelte ricordate tornando indietro da un set o da una carta.
const listView = { lang: "en", onlyMine: false, sort: "release", desc: true };
const setView = { sort: "number", desc: false, filter: "all" };

export function SetsScreen({ route }: { route: string[] }) {
  // #/sets  oppure  #/sets/en/sv03.5
  return route.length >= 3 ? <SetView lang={route[1]} id={route.slice(2).join("/")} /> : <SetList />;
}

const total = (s: SetBrief) => s.total || s.official || 0;
const progress = (s: SetBrief) => (total(s) ? s.owned / total(s) : 0);

function SetRow({ s, lang }: { s: SetBrief; lang: string }) {
  const pctOwned = Math.min(100, Math.round(progress(s) * 100));
  return (
    <button class="set-item" onClick={() => go(`sets/${lang}/${encodeURIComponent(s.id)}`)}>
      <div class="set-logo-box"><SetLogo logo={s.logo} symbol={s.symbol} code={s.id} /></div>
      <div class="set-main">
        <div class="strong">{s.name}</div>
        <div class="muted small">{s.id} · {plural(total(s), "carta", "carte")}</div>
        {s.owned > 0 && <div class="progress"><div style={{ width: `${pctOwned}%` }} /></div>}
      </div>
      <div class="set-count">
        {s.owned > 0 ? <><b>{s.owned}</b><span>/{total(s)}</span></> : <span class="muted">—</span>}
      </div>
    </button>
  );
}

function SetList() {
  const [lang, setLang] = useState(listView.lang);
  const [data, setData] = useState<SeriesGroup[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [q, setQ] = useState("");
  const [onlyMine, setOnlyMine] = useState(listView.onlyMine);
  const [sort, setSort] = useState(listView.sort);
  const [desc, setDesc] = useState(listView.desc);

  useEffect(() => {
    setData(null);
    setError(null);
    api.sets(lang).then((r) => setData(r.series)).catch((e) => setError((e as Error).message));
  }, [lang]);
  useEffect(() => { Object.assign(listView, { lang, onlyMine, sort, desc }); }, [lang, onlyMine, sort, desc]);

  const keep = (s: SetBrief) => {
    const needle = q.trim().toLowerCase();
    return (!onlyMine || s.owned > 0) && (!needle || `${s.name} ${s.id}`.toLowerCase().includes(needle));
  };
  const groups = useMemo(() => {
    const g = (data ?? []).map((x) => ({ ...x, sets: x.sets.filter(keep) })).filter((x) => x.sets.length);
    return desc ? g : [...g].reverse().map((x) => ({ ...x, sets: [...x.sets].reverse() }));
  }, [data, q, onlyMine, desc]);
  const flat = useMemo(() => {
    const all = (data ?? []).flatMap((g) => g.sets).filter(keep);
    const keys: Record<string, (s: SetBrief) => string | number> = {
      name: (s) => s.name, progress, owned: (s) => s.owned, size: total,
    };
    return sortBy(all, keys[sort] ?? keys.name, desc);
  }, [data, q, onlyMine, sort, desc]);

  return (
    <>
      <Header title="Espansioni" />
      <div class="searchbar">
        <Icon name="search" size={20} />
        <input type="search" placeholder="Cerca un set per nome o codice" value={q}
          onInput={(e) => setQ((e.target as HTMLInputElement).value)} />
      </div>
      <div class="chips">
        {LANGS.map((l) => <button class={`chip ${lang === l.id ? "on" : ""}`} onClick={() => setLang(l.id)}>{l.label}</button>)}
        <span class="chip-sep" />
        <button class={`chip ${onlyMine ? "on" : ""}`} onClick={() => setOnlyMine(!onlyMine)}>Solo i miei</button>
      </div>
      <SortBar options={LIST_SORTS} value={sort} desc={desc} onChange={(s, d) => { setSort(s); setDesc(d); }} />
      {error && <p class="error pad">{error}</p>}
      {!data && !error && <Spinner label="Carico le espansioni…" />}
      {data && (sort === "release" ? groups.length : flat.length) === 0 && <p class="muted pad">Nessun set con questi filtri.</p>}
      {sort === "release"
        ? groups.map((g) => (
            <section>
              <h2 class="section">{g.name}</h2>
              <div class="list">{g.sets.map((s) => <SetRow s={s} lang={lang} />)}</div>
            </section>
          ))
        : <div class="list top">{flat.map((s) => <SetRow s={s} lang={lang} />)}</div>}
    </>
  );
}

function SetView({ lang, id }: { lang: string; id: string }) {
  const [data, setData] = useState<SetDetail | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [filter, setFilter] = useState(setView.filter);
  const [sort, setSort] = useState(setView.sort);
  const [desc, setDesc] = useState(setView.desc);
  const [q, setQ] = useState("");

  useEffect(() => {
    setData(null);
    api.set(lang, id).then(setData).catch((e) => setError((e as Error).message));
  }, [lang, id]);
  useEffect(() => { Object.assign(setView, { filter, sort, desc }); }, [filter, sort, desc]);

  const cards = useMemo(() => {
    if (!data) return [];
    const needle = q.trim().toLowerCase();
    const rows = data.cards.filter((c) => (filter === "all" || (filter === "owned" ? c.owned : !c.owned))
      && (!needle || `${c.name} ${c.number ?? ""}`.toLowerCase().includes(needle)));
    const keys: Record<string, (c: CardSummary) => string | number> = {
      number: (c) => c.number ?? "", name: (c) => c.name, owned: (c) => c.owned ?? 0,
    };
    return sortBy(rows, keys[sort] ?? keys.number, desc);
  }, [data, filter, sort, desc, q]);

  if (error) return <><Header title="Espansione" /><p class="error pad">{error}</p></>;
  if (!data) return <Spinner label="Carico il set…" />;

  const pctOwned = data.total ? Math.round((data.owned_unique / data.total) * 100) : 0;
  return (
    <>
      <div class="screen-head">
        <button class="round" onClick={() => go("sets")} aria-label="Indietro"><Icon name="back" /></button>
      </div>
      <section class="set-hero">
        <SetLogo logo={data.logo} symbol={data.symbol} code={data.code} class="set-hero-logo" />
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
      <div class="searchbar small">
        <Icon name="search" size={18} />
        <input type="search" placeholder="Cerca nel set (nome o numero)" value={q}
          onInput={(e) => setQ((e.target as HTMLInputElement).value)} />
      </div>
      <div class="chips">
        {FILTERS.map((f) => <button class={`chip ${filter === f.id ? "on" : ""}`} onClick={() => setFilter(f.id)}>{f.label}</button>)}
      </div>
      <SortBar options={CARD_SORTS} value={sort} desc={desc} onChange={(s, d) => { setSort(s); setDesc(d); }} />
      {cards.length === 0 && (
        <p class="muted pad">{q ? "Nessuna carta trovata nel set." : filter === "owned" ? "Non hai ancora carte di questo set." : "Hai tutte le carte del set!"}</p>
      )}
      <CardGrid cards={cards} dimMissing={data.owned_unique > 0} hideSet />
    </>
  );
}
