import { useEffect, useMemo, useRef, useState } from "preact/hooks";
import { api, type CollectionDetail, type CollectionItem, type CollectionSummary, type ImportReport } from "../api";
import { CATALOG_BADGE, date, LANG_CHIPS, pct, plural, price, trendClass } from "../format";
import { openCard } from "../nav";
import { CardImage, Header, Icon, Spinner } from "../ui";
import { TrackedList } from "./Tracked";

const SORTS = [
  { id: "value", label: "Valore" },
  { id: "name", label: "Nome" },
  { id: "set", label: "Set" },
  { id: "recent", label: "Recenti" },
];
const FOLLOWED = -1; // "collezione" speciale: le carte seguite

// Si ricorda la collezione aperta tornando da una carta.
let lastSelected: number | null = null;

export function CollectionScreen() {
  const [list, setList] = useState<CollectionSummary[] | null>(null);
  const [selected, setSelected] = useState<number | null>(lastSelected);
  const [error, setError] = useState<string | null>(null);
  const [report, setReport] = useState<ImportReport | null>(null);
  const [importing, setImporting] = useState(false);
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

  const logout = async () => {
    await api.logout().catch(() => {});
    location.reload();
  };

  return (
    <>
      <Header title="Collezione" right={<>
        <button class="round" onClick={() => fileInput.current?.click()} aria-label="Importa da file"><Icon name="upload" /></button>
        <button class="round" onClick={logout} aria-label="Esci"><Icon name="logout" /></button>
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
            <button class={`chip ${selected === c.id ? "on" : ""}`} onClick={() => setSelected(c.id)}>{c.name}</button>
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
    </>
  );
}

function CollectionView({ id, onChanged }: { id: number; onChanged: () => void }) {
  const [data, setData] = useState<CollectionDetail | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [sort, setSort] = useState("value");
  const [lang, setLang] = useState("all");
  const [q, setQ] = useState("");
  const [onlyReview, setOnlyReview] = useState(false);

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
    let rows = data.items.filter((i) => (lang === "all" || i.lang === lang) && (!onlyReview || i.needs_review)
      && (!needle || `${i.name} ${i.set_name ?? ""} ${i.number_label ?? ""}`.toLowerCase().includes(needle)));
    const by: Record<string, (a: CollectionItem, b: CollectionItem) => number> = {
      value: (a, b) => (b.total ?? -1) - (a.total ?? -1),
      name: (a, b) => a.name.localeCompare(b.name, "it"),
      set: (a, b) => (a.set_name ?? "").localeCompare(b.set_name ?? "", "it")
        || (parseInt(a.number_label ?? "0") - parseInt(b.number_label ?? "0")),
      recent: (a, b) => (b.added_at ?? "").localeCompare(a.added_at ?? ""),
    };
    rows = [...rows].sort(by[sort]);
    return rows;
  }, [data, sort, lang, q, onlyReview]);

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
        <Sparkline points={data.history.map((h) => h.value)} />
        {data.pending_prices > 0 && <p class="value-note"><span class="dot" /> Aggiorno i prezzi di {plural(data.pending_prices, "carta", "carte")}…</p>}
        {data.unpriced > 0 && !data.pending_prices && (
          <p class="value-note">{plural(data.unpriced, "carta", "carte")} senza prezzo su Cardmarket: non conteggiate.</p>
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
      <div class="chips">
        {SORTS.map((s) => <button class={`chip ${sort === s.id ? "on" : ""}`} onClick={() => setSort(s.id)}>{s.label}</button>)}
        {langs.length > 1 && <span class="chip-sep" />}
        {langs.length > 1 && ["all", ...langs].map((l) => (
          <button class={`chip ${lang === l ? "on" : ""}`} onClick={() => setLang(l)}>
            {l === "all" ? "Tutte" : `${LANG_CHIPS.find((x) => x.code === l)?.flag ?? ""} ${l.toUpperCase()}`}
          </button>
        ))}
      </div>

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

function Sparkline({ points }: { points: number[] }) {
  if (points.length < 2) return null;
  const w = 300, h = 44;
  const min = Math.min(...points), max = Math.max(...points);
  const span = max - min || 1;
  const d = points.map((p, i) => `${i ? "L" : "M"}${(i / (points.length - 1)) * w},${h - 4 - ((p - min) / span) * (h - 8)}`).join(" ");
  const up = points[points.length - 1] >= points[0];
  return (
    <svg class="spark" viewBox={`0 0 ${w} ${h}`} preserveAspectRatio="none" aria-hidden="true">
      <path d={d} fill="none" stroke={up ? "var(--up)" : "var(--down)"} stroke-width="2.5" stroke-linejoin="round" vector-effect="non-scaling-stroke" />
    </svg>
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
