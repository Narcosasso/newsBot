import { useEffect, useMemo, useRef, useState } from "preact/hooks";
import { api, type CollectionDetail, type CollectionItem, type CollectionSummary, type ImportReport } from "../api";
import { CATALOG_BADGE, date, LANG_CHIPS, pct, plural, price, trendClass } from "../format";
import { openCard } from "../nav";
import { CardImage, Header, Icon, SortBar, type SortOption, Spinner, sortBy } from "../ui";
import { SettingsSheet } from "./Settings";
import { TrackedList } from "./Tracked";
import { PriceChart } from "../chart";

const SORTS: SortOption[] = [
  { id: "value", label: "Valore totale", desc: true },
  { id: "unit", label: "Prezzo per carta", desc: true },
  { id: "name", label: "Nome" },
  { id: "set", label: "Set e numero" },
  { id: "rarity", label: "Rarità" },
  { id: "qty", label: "Quantità", desc: true },
  { id: "recent", label: "Data di aggiunta", desc: true },
];
// Ordinamento e filtri restano uguali tornando da una carta.
const view = { sort: "value", desc: true, lang: "all", dupes: false };
const FOLLOWED = -1; // "collezione" speciale: le carte seguite

// Si ricorda la collezione aperta tornando da una carta.
let lastSelected: number | null = null;

export function CollectionScreen() {
  const [list, setList] = useState<CollectionSummary[] | null>(null);
  const [selected, setSelected] = useState<number | null>(lastSelected);
  const [error, setError] = useState<string | null>(null);
  const [report, setReport] = useState<ImportReport | null>(null);
  const [importing, setImporting] = useState(false);
  const [settings, setSettings] = useState(false);
  const fileInput = useRef<HTMLInputElement>(null);

  const loadList = () =>
    api.collections().then((r) => {
      setList(r.collections);
      setSelected((cur) => {
        const keep = cur === FOLLOWED || r.collections.some((c) => c.id === cur);
        return keep ? cur : r.collections[0]?.id ?? null;
      });
    }).catch((e) => setError((e as Error).message));

  useEffect(() => { loadList(); }, []);
  useEffect(() => { lastSelected = selected; }, [selected]);

  const onFile = async (e: Event) => {
    const input = e.target as HTMLInputElement;
    const file = input.files?.[0];
    input.value = "";
    if (!file) return;
    setImporting(true);
    setError(null);
    try {
      const r = await api.importCollection(await file.text());
      setReport(r);
      setSelected(r.collection_id);
      await loadList();
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setImporting(false);
    }
  };

  return (
    <>
      <Header title="Collezione" right={<>
        <button class="round" onClick={() => fileInput.current?.click()} aria-label="Importa da file"><Icon name="upload" /></button>
        <button class="round" onClick={() => setSettings(true)} aria-label="Impostazioni"><Icon name="gear" /></button>
      </>} />
      <input ref={fileInput} type="file" accept=".json,application/json" hidden onChange={onFile} />

      {importing && <Spinner label="Importo la collezione…" />}
      {error && <p class="error pad">{error}</p>}
      {!list && !error && <Spinner />}

      {list && list.length === 0 && !importing && (
        <div class="empty">
          <Icon name="folder" size={40} />
          <h2>La tua collezione è vuota</h2>
          <p class="muted">Importa il file esportato da MyDex, oppure apri una carta e tocca <b>Aggiungi alla collezione</b>.</p>
          <button class="btn primary" onClick={() => fileInput.current?.click()}><Icon name="upload" size={18} /> Importa da file</button>
        </div>
      )}

      {list && (list.length > 0 || selected === FOLLOWED) && (
        <div class="chips">
          {list.map((c) => (
            <button class={`chip ${selected === c.id ? "on" : ""}`} onClick={() => setSelected(c.id)}>{c.kind === "wishlist" ? "❤ " : ""}{c.name}</button>
          ))}
          <button class={`chip ${selected === FOLLOWED ? "on" : ""}`} onClick={() => setSelected(FOLLOWED)}>🔔 Seguite</button>
        </div>
      )}
      {list && list.length === 0 && selected !== FOLLOWED && (
        <button class="link-more" onClick={() => setSelected(FOLLOWED)}>Vedi le carte che segui ›</button>
      )}

      {selected === FOLLOWED && <TrackedList />}
      {selected !== null && selected !== FOLLOWED && (
        <CollectionView key={selected} id={selected} onChanged={loadList} />
      )}

      {report && <ImportResult report={report} onClose={() => setReport(null)} />}
      {settings && <SettingsSheet onClose={() => setSettings(false)} />}
    </>
  );
}

function CollectionView({ id, onChanged }: { id: number; onChanged: () => void }) {
  const [data, setData] = useState<CollectionDetail | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [sort, setSort] = useState(view.sort);
  const [desc, setDesc] = useState(view.desc);
  const [lang, setLang] = useState(view.lang);
  const [dupes, setDupes] = useState(view.dupes);
  const [q, setQ] = useState("");
  const [onlyReview, setOnlyReview] = useState(false);
  useEffect(() => { Object.assign(view, { sort, desc, lang, dupes }); }, [sort, desc, lang, dupes]);

  const load = () => api.collection(id).then(setData).catch((e) => setError((e as Error).message));

  useEffect(() => { load(); }, [id]);
  // Dopo un import i prezzi arrivano in qualche secondo: ricarico finché non ci sono tutti.
  useEffect(() => {
    if (!data?.pending_prices) return;
    const t = setTimeout(load, 4000);
    return () => clearTimeout(t);
  }, [data]);

  const items = useMemo(() => {
    if (!data) return [];
    const needle = q.trim().toLowerCase();
    const rows = data.items.filter((i) => (lang === "all" || i.lang === lang) && (!onlyReview || i.needs_review)
      && (!dupes || i.quantity > 1)
      && (!needle || `${i.name} ${i.set_name ?? ""} ${i.number_label ?? ""} ${i.rarity ?? ""}`.toLowerCase().includes(needle)));
    const num = (i: CollectionItem) => parseInt(i.number_label ?? "", 10) || 0;
    const keys: Record<string, (i: CollectionItem) => string | number | null> = {
      value: (i) => i.total, unit: (i) => i.unit_price, name: (i) => i.name,
      set: (i) => `${i.set_name ?? ""} ${String(num(i)).padStart(4, "0")}`, rarity: (i) => i.rarity,
      qty: (i) => i.quantity, recent: (i) => i.added_at,
    };
    return sortBy(rows, keys[sort] ?? keys.value, desc);
  }, [data, sort, desc, lang, q, onlyReview, dupes]);

  if (error) return <p class="error pad">{error}</p>;
  if (!data) return <Spinner />;

  const langs = [...new Set(data.items.map((i) => i.lang))];
  const review = data.items.filter((i) => i.needs_review).length;
  const first = data.history.find((h) => h.cards === data.cards) ?? data.history[0];
  const change = first && first.value ? ((data.value - first.value) / first.value) * 100 : null;

  const rename = async () => {
    const name = prompt("Nuovo nome della collezione", data.name)?.trim();
    if (!name || name === data.name) return;
    await api.renameCollection(id, name);
    await load();
    onChanged();
  };
  const remove = async () => {
    if (!confirm(`Eliminare «${data.name}» e le sue ${data.cards} carte? Non si può annullare.`)) return;
    await api.deleteCollection(id);
    onChanged();
  };
  const refresh = async () => {
    await api.refreshCollection(id);
    setData({ ...data, pending_prices: data.unique });
    setTimeout(load, 4000);
  };

  return (
    <>
      <section class="value-card">
        <div class="value-label">Valore della collezione</div>
        <div class="value-main">{price(data.value)}</div>
        <div class="value-sub">
          {plural(data.cards, "carta", "carte")} · {plural(data.unique, "diversa", "diverse")}
          {change !== null && data.history.length > 1 && (
            <span class={`trend ${trendClass(change)}`}>{pct(change)} <small>dal {date(first!.day)}</small></span>
          )}
        </div>
        <PriceChart points={data.history.map((h) => ({ day: h.day, value: h.value }))} height={90} />
        {data.pending_prices > 0 && <p class="value-note"><span class="dot" /> Aggiorno i prezzi di {plural(data.pending_prices, "carta", "carte")}…</p>}
        {data.unpriced > 0 && !data.pending_prices && (
          <p class="value-note">{plural(data.unpriced, "carta", "carte")} senza prezzo su Cardmarket: non conteggiate.</p>
        )}
        {data.kind !== "wishlist" && (
          <div class="privacy-row">
            <button class={`mini ${data.visibility === "friends" ? "gold" : ""}`} onClick={async () => {
              const r = await api.privacy(id, { visibility: data.visibility === "friends" ? "private" : "friends" });
              setData({ ...data, ...r });
            }}>{data.visibility === "friends" ? "👥 Visibile agli amici" : "🔒 Privata"}</button>
            {data.visibility === "friends" && (
              <button class="mini" onClick={async () => {
                const r = await api.privacy(id, { show_values: !data.show_values });
                setData({ ...data, ...r });
              }}>{data.show_values ? "€ Valori visibili" : "€ Valori nascosti"}</button>
            )}
          </div>
        )}
        <div class="value-actions">
          <button class="mini" onClick={refresh}><Icon name="refresh" size={16} /> Aggiorna prezzi</button>
          <button class="mini" onClick={rename}>Rinomina</button>
          <button class="mini danger" onClick={remove}>Elimina</button>
        </div>
      </section>

      {review > 0 && (
        <button class={`banner review ${onlyReview ? "on" : ""}`} onClick={() => setOnlyReview(!onlyReview)}>
          <b>{plural(review, "carta da verificare", "carte da verificare")}</b>: abbinate per nome durante l'import.
          {onlyReview ? " Tocca per vederle tutte." : " Tocca per vederle."}
        </button>
      )}

      <div class="searchbar small">
        <Icon name="search" size={18} />
        <input type="search" placeholder="Cerca nella collezione" value={q}
          onInput={(e) => setQ((e.target as HTMLInputElement).value)} />
      </div>
      <SortBar options={SORTS} value={sort} desc={desc} onChange={(s, d) => { setSort(s); setDesc(d); }} />
      <div class="chips">
        <button class={`chip ${dupes ? "on" : ""}`} onClick={() => setDupes(!dupes)}>Doppioni</button>
        {langs.length > 1 && <span class="chip-sep" />}
        {langs.length > 1 && ["all", ...langs].map((l) => (
          <button class={`chip ${lang === l ? "on" : ""}`} onClick={() => setLang(l)}>
            {l === "all" ? "Tutte le lingue" : `${LANG_CHIPS.find((x) => x.code === l)?.flag ?? ""} ${l.toUpperCase()}`}
          </button>
        ))}
      </div>
      {(q || dupes || lang !== "all" || onlyReview) && (
        <p class="muted small pad">{items.length} {items.length === 1 ? "carta" : "carte"} · valore {price(items.reduce((s, i) => s + (i.total ?? 0), 0))}</p>
      )}

      {items.length === 0 && <p class="muted pad">Nessuna carta con questi filtri.</p>}
      <div class="grid">
        {items.map((i) => (
          <button class="tile" onClick={() => openCard(i.catalog_lang, i.card_id)}>
            <div class="tile-img">
              <CardImage src={i.image} alt={i.name} />
              {i.quantity > 1 && <span class="qty">×{i.quantity}</span>}
              {i.needs_review && <span class="flag-review">?</span>}
            </div>
            <span class="tile-name">{i.name}</span>
            <span class="tile-sub">
              {CATALOG_BADGE[i.catalog_lang] && <span class="badge">{CATALOG_BADGE[i.catalog_lang]}</span>}
              {i.number_label ?? ""}
            </span>
            <span class="tile-price">{i.unit_price !== null ? price(i.total) : "—"}</span>
          </button>
        ))}
      </div>
    </>
  );
}

function ImportResult({ report, onClose }: { report: ImportReport; onClose: () => void }) {
  return (
    <div class="modal" onClick={onClose}>
      <div class="modal-card" onClick={(e) => e.stopPropagation()}>
        <h2>Import completato</h2>
        <p>In <b>{report.collection_name}</b>: {plural(report.cards, "carta", "carte")} ({plural(report.imported, "diversa", "diverse")}).
          I prezzi si aggiornano in qualche secondo.</p>
        {report.review.length > 0 && (
          <>
            <h3>Da verificare ({report.review.length})</h3>
            <p class="muted small">Il numero non corrispondeva: le ho abbinate per nome. Aprile e conferma.</p>
            <ul class="report-list">
              {report.review.map((r) => (
                <li><button class="link" onClick={() => { onClose(); openCard(r.catalog_lang, r.card_id); }}>
                  {r.file} → {r.matched}</button></li>
              ))}
            </ul>
          </>
        )}
        {report.unmatched.length > 0 && (
          <>
            <h3>Non importate ({report.unmatched.length})</h3>
            <ul class="report-list">
              {report.unmatched.map((u) => <li>{u.name} · {u.set} {u.number} ×{u.quantity}<br /><small class="muted">{u.reason}</small></li>)}
            </ul>
          </>
        )}
        <button class="btn primary" onClick={onClose}>Ok</button>
      </div>
    </div>
  );
}
