import { useEffect, useState } from "preact/hooks";
import { api, type Analysis, type CardDetail, type CollectionSummary, type Graded, type OwnedItem, type PriceGroup,
  type TrackingInfo } from "../api";
import { CATALOG_BADGE, date, LANG_CHIPS, pct, plural, price, rarity, STAGE_IT, trendClass, TYPE_IT } from "../format";
import { CardImage, Icon, Spinner } from "../ui";
import { searchFor } from "./Search";

export function CardDetailScreen({ lang, id, onClose }: { lang: string; id: string; onClose: () => void }) {
  const [detail, setDetail] = useState<CardDetail | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [vIdx, setVIdx] = useState(0);
  const [graded, setGraded] = useState<Graded | null>(null);
  const [toast, setToast] = useState<string | null>(null);

  useEffect(() => {
    setDetail(null);
    setError(null);
    setGraded(null);
    setVIdx(0);
    api.card(lang, id).then(setDetail).catch((e) => setError((e as Error).message));
  }, [lang, id]);

  useEffect(() => {
    if (!detail) return;
    const variant = detail.variants[0]?.variant ?? "holo";
    api.graded(lang, id, variant).then(setGraded).catch(() =>
      setGraded({ available: false, reason: "Prezzi gradati non disponibili in questo momento." }));
  }, [detail?.id]);

  const flash = (text: string) => {
    setToast(text);
    setTimeout(() => setToast(null), 2500);
  };

  const share = async () => {
    if (!detail) return;
    const trend = detail.variants[vIdx]?.groups[0]?.cardmarket?.trend;
    const text = `${detail.label}${trend ? ` — ${price(trend)} su Cardmarket` : ""}`;
    try {
      if (navigator.share) await navigator.share({ title: detail.name, text });
      else {
        await navigator.clipboard.writeText(text);
        flash("Copiato negli appunti");
      }
    } catch {
      /* condivisione annullata */
    }
  };

  const variant = detail?.variants[vIdx];

  return (
    <div class="sheet">
      <div class="sheet-bar">
        <button class="round" onClick={onClose} aria-label="Chiudi"><Icon name="close" /></button>
        <h1 class="sheet-title">{detail?.name ?? ""}</h1>
        <button class="round" onClick={share} disabled={!detail} aria-label="Condividi"><Icon name="share" /></button>
      </div>

      <div class="sheet-body">
        {error && <p class="error pad">{error}</p>}
        {!detail && !error && <Spinner label="Carico la carta…" />}
        {detail && (
          <>
            <div class="hero">
              <CardImage src={detail.image} alt={detail.name} class="big" />
              {detail.image_from_other_lang && (
                <p class="hero-note">Foto della versione {detail.catalog_lang === "zh-tw" ? "giapponese" : "inglese"}: quella in questa lingua non è disponibile.</p>
              )}
            </div>

            <div class="card-meta">
              <div class="title-row">
                <span class="number">{detail.number}{detail.set.official ? <small>/{detail.set.official}</small> : null}</span>
                {CATALOG_BADGE[detail.catalog_lang] && <span class="badge big">{CATALOG_BADGE[detail.catalog_lang]}</span>}
                {rarity(detail.rarity) && <span class="pill gold">{rarity(detail.rarity)}</span>}
              </div>
              <div class="set-line">{detail.set.name} · {detail.set.code}</div>
            </div>

            <div class="info-list">
              {detail.illustrator && (
                <button class="info-row" onClick={() => searchFor(detail.illustrator!)}>
                  <Icon name="brush" size={20} />
                  <span class="info-text"><small>Illustratore</small>{detail.illustrator}</span>
                  <Icon name="chevron" size={18} />
                </button>
              )}
              {detail.dex_ids.map((n) => (
                <button class="info-row" onClick={() => searchFor(`#${n}`)}>
                  <Icon name="dex" size={20} />
                  <span class="info-text"><small>Pokédex n. {n}</small>Tutte le carte di questo Pokémon</span>
                  <Icon name="chevron" size={18} />
                </button>
              ))}
            </div>

            {detail.variants.length > 1 && (
              <div class="segmented">
                {detail.variants.map((v, i) => (
                  <button class={i === vIdx ? "on" : ""} onClick={() => setVIdx(i)}>{v.label}</button>
                ))}
              </div>
            )}

            <section class="panel">
              <h2>Prezzi {variant && detail.variants.length === 1 ? <span class="pill">{variant.label}</span> : null}</h2>
              {variant?.groups.map((g) => <PriceBlock group={g} />)}
              <PriceNotes groups={variant?.groups ?? []} />
            </section>

            <AnalysisPanel key={`${detail.id}:${variant?.variant}`} detail={detail} variant={variant?.variant ?? "holo"} />

            <GradedPanel graded={graded} chinese={detail.catalog_lang === "zh-tw"} />

            <OwnedPanel detail={detail} onChanged={(owned, msg) => {
              setDetail({ ...detail, owned });
              if (msg) flash(msg);
            }} />

            <FollowPanel detail={detail} variant={variant?.variant ?? "holo"}
              psaAvailable={!!graded?.grades?.some((g) => g.company === "PSA" && g.grade === "10")}
              onSaved={(msg, tracking) => {
                setDetail({ ...detail, tracking });
                flash(msg);
              }} />

            <StatsPanel detail={detail} />

            <section class="panel">
              <h2>Espansione</h2>
              <div class="set-row">
                {detail.set.logo && <img class="set-logo" src={detail.set.logo} alt="" loading="lazy"
                  onError={(e) => ((e.target as HTMLImageElement).style.display = "none")} />}
                <div>
                  <div class="strong">{detail.set.name} <span class="code">{detail.set.code}</span></div>
                  <div class="muted">{detail.set.serie ?? ""}{detail.set.release_date ? ` · uscita ${date(detail.set.release_date)}` : ""}</div>
                  <div class="muted">{detail.set.official ?? "?"} carte{detail.set.total && detail.set.total !== detail.set.official ? ` (+${detail.set.total - (detail.set.official ?? 0)} segrete)` : ""}</div>
                </div>
              </div>
              <button class="btn ghost" onClick={() => searchFor(`set:${detail.set.id}`)}>Vedi tutte le carte del set</button>
            </section>

            <section class="panel">
              <h2>Vedi sui marketplace</h2>
              <div class="markets">
                {withTcgplayer(detail.marketplaces, graded).map((m) => (
                  <a class="info-row" href={m.url} target="_blank" rel="noopener noreferrer">
                    <span class="info-text">{m.name}</span><Icon name="link" size={18} /></a>
                ))}
              </div>
            </section>
          </>
        )}
      </div>
      {toast && <div class="toast">{toast}</div>}
    </div>
  );
}

function PriceBlock({ group }: { group: PriceGroup }) {
  const cm = group.cardmarket;
  const tp = group.tcgplayer;
  const twin = group.card_label?.split(" · ")[1];
  return (
    <div class="price-block">
      <div class="price-head">{group.label}</div>
      {group.estimated && twin && <div class="price-twin">Abbinata a: {twin}</div>}
      {cm ? (
        <>
          <div class="price-main">{price(cm.trend ?? cm.avg7 ?? cm.avg, cm.currency)}</div>
          <div class="price-caption">prezzo di mercato su Cardmarket</div>
          <div class="price-grid">
            <div><small>Minimo</small>{price(cm.low, cm.currency)}</div>
            <div><small>Media vendite</small>{price(cm.avg, cm.currency)}</div>
            <div><small>Media 30 gg</small>{price(cm.avg30, cm.currency)}</div>
          </div>
          <div class="price-trend">
            <Trend value={cm.change_7d} label="7 giorni" />
            <Trend value={cm.change_30d} label="30 giorni" />
          </div>
        </>
      ) : (
        <p class="info-box"><Icon name="info" size={18} />
          <span>{group.notes[0] ?? "Nessun prezzo su Cardmarket per questa versione."}</span></p>
      )}
      {tp && (tp.market !== null || tp.low !== null) && (
        <div class="price-extra">🇺🇸 TCGplayer <b>{price(tp.market, tp.currency)}</b>
          {tp.low !== null && <span class="muted"> · da {price(tp.low, tp.currency)}</span>}</div>
      )}
    </div>
  );
}

function Trend({ value, label }: { value: number | null; label: string }) {
  const cls = trendClass(value);
  const arrow = cls === "up" ? "↗" : cls === "down" ? "↘" : "→";
  return <span class={`trend ${cls}`}>{arrow} {pct(value)} <small>{label}</small></span>;
}

function PriceNotes({ groups }: { groups: PriceGroup[] }) {
  const updated = groups.map((g) => g.cardmarket?.updated).filter(Boolean).sort().pop();
  return (
    <div class="notes">
      {groups.some((g) => g.aggregated) && (
        <p>ITA, ENG, DEU, FRA, SPA e POR hanno lo stesso prezzo: Cardmarket le vende come un unico prodotto.</p>
      )}
      {groups.some((g) => g.estimated) && <p>Le versioni «abbinate» sono la stessa illustrazione in un altro set.</p>}
      {updated && <p>Aggiornati il {date(updated, true)}. Andamento rispetto alla media delle vendite.</p>}
    </div>
  );
}

function GradedPanel({ graded, chinese }: { graded: Graded | null; chinese: boolean }) {
  const [company, setCompany] = useState("PSA");
  const companies = graded?.companies ?? [];
  const current = companies.includes(company) ? company : companies[0];
  const rows = (graded?.grades ?? []).filter((g) => g.company === current);
  return (
    <section class="panel">
      <h2>Carte gradate</h2>
      {!graded && <Spinner />}
      {graded && !graded.available && <p class="muted">{graded.reason}</p>}
      {graded?.available && companies.length === 0 && <p class="muted">Nessuna vendita gradata registrata finora.</p>}
      {graded?.available && companies.length > 0 && (
        <>
          <div class="chips">
            {companies.map((c) => <button class={`chip ${c === current ? "on" : ""}`} onClick={() => setCompany(c)}>{c}</button>)}
          </div>
          <div class="grades">
            {rows.map((g) => (
              <div class="grade">
                <div class="grade-head">{g.company} <b>{g.grade}</b></div>
                <div class="grade-price">{g.price_eur !== null ? price(g.price_eur) : price(g.price_usd, "USD")}</div>
                {g.price_eur !== null && <div class="grade-sub">{price(g.price_usd, "USD")}</div>}
                <div class="grade-sub">{plural(g.sales, "vendita", "vendite")}
                  {g.trend === "up" ? <span class="up"> ↗</span> : g.trend === "down" ? <span class="down"> ↘</span> : ""}</div>
              </div>
            ))}
          </div>
          <div class="notes">
            <p>{chinese
              ? "Le carte cinesi gradate non hanno vendite registrate: come riferimento, la stampa giapponese venduta su eBay e Fanatics negli USA."
              : `Stampa ${graded.print}: vendite su eBay e Fanatics negli USA.`}</p>
            {graded.usd_per_eur
              ? <p>In euro al cambio BCE del {date(graded.fx_date)} (1 € = {graded.usd_per_eur.toLocaleString("it-IT")} $).</p>
              : <p>Cambio euro non disponibile ora: prezzi in dollari.</p>}
          </div>
        </>
      )}
    </section>
  );
}

function FollowPanel({ detail, variant, psaAvailable, onSaved }: {
  detail: CardDetail; variant: string; psaAvailable: boolean;
  onSaved: (msg: string, tracking: TrackingInfo[]) => void;
}) {
  const current = detail.tracking.find((t) => t.variant === variant);
  const [editing, setEditing] = useState(false);
  const [langs, setLangs] = useState<string[]>(current?.langs ?? ["it"]);
  const [psa, setPsa] = useState<boolean>(current?.psa ?? false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    setLangs(current?.langs ?? ["it"]);
    setPsa(current?.psa ?? false);
    setEditing(false);
  }, [variant, current?.id]);

  const toggle = (code: string) =>
    setLangs((l) => (l.includes(code) ? l.filter((x) => x !== code) : [...l, code]));

  const save = async () => {
    setBusy(true);
    setError(null);
    try {
      const r = await api.track({ card_id: detail.id, catalog_lang: detail.catalog_lang, variant, langs, psa });
      const others = detail.tracking.filter((t) => t.id !== r.tracking.id);
      onSaved("🔔 Avvisi attivi", [...others, r.tracking]);
      setEditing(false);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  };

  const stop = async () => {
    if (!current) return;
    setBusy(true);
    try {
      await api.untrack(current.id);
      onSaved("Avvisi disattivati", detail.tracking.filter((t) => t.id !== current.id));
    } finally {
      setBusy(false);
    }
  };

  return (
    <section class="panel">
      <h2><Icon name="bell" size={20} /> Avvisi prezzo</h2>
      {!editing && current && (
        <>
          <p>Ti avviso quando il prezzo cambia per: <b>{current.langs.map((c) => LANG_CHIPS.find((x) => x.code === c)?.label ?? c).join(", ")}</b>
            {current.psa ? <> e <b>PSA 10</b></> : null}.</p>
          <div class="row gap">
            <button class="btn ghost" onClick={() => setEditing(true)}>Modifica</button>
            <button class="btn danger" onClick={stop} disabled={busy}>Smetti di seguire</button>
          </div>
        </>
      )}
      {!editing && !current && (
        <>
          <p class="muted">Ricevi un avviso quando il prezzo sale o scende oltre la tua soglia.</p>
          <button class="btn primary" onClick={() => setEditing(true)}>Segui questa carta</button>
        </>
      )}
      {editing && (
        <>
          <p class="muted">Lingue da seguire</p>
          <div class="chips wrap">
            {LANG_CHIPS.map((l) => (
              <button class={`chip ${langs.includes(l.code) ? "on" : ""}`} onClick={() => toggle(l.code)}>{l.flag} {l.label}</button>
            ))}
          </div>
          {psaAvailable && (
            <label class="switch">
              <input type="checkbox" checked={psa} onChange={(e) => setPsa((e.target as HTMLInputElement).checked)} />
              <span>Segui anche il prezzo <b>PSA 10</b></span>
            </label>
          )}
          {error && <p class="error">{error}</p>}
          <div class="row gap">
            <button class="btn primary" onClick={save} disabled={busy || langs.length === 0}>{busy ? "Salvo…" : "Salva"}</button>
            <button class="btn ghost" onClick={() => setEditing(false)}>Annulla</button>
          </div>
        </>
      )}
    </section>
  );
}

function StatsPanel({ detail }: { detail: CardDetail }) {
  const s = detail.stats;
  if (!s.hp && !s.types.length && !s.retreat) return null;
  const t = (x: string) => TYPE_IT[x] ?? x;
  return (
    <section class="panel">
      <h2>Statistiche</h2>
      <div class="stats">
        {s.hp && <span class="pill">PS {s.hp}</span>}
        {s.types.map((x) => <span class="pill">{t(x)}</span>)}
        {s.stage && <span class="pill">{STAGE_IT[s.stage] ?? s.stage}</span>}
        {s.regulation_mark && <span class="pill">Regolamento {s.regulation_mark}</span>}
      </div>
      <dl class="kv">
        {s.evolve_from && <><dt>Si evolve da</dt><dd>{s.evolve_from}</dd></>}
        <dt>Debolezza</dt><dd>{s.weaknesses.length ? s.weaknesses.map((w) => `${t(w.type)} ${w.value ?? ""}`).join(", ") : "—"}</dd>
        <dt>Resistenza</dt><dd>{s.resistances.length ? s.resistances.map((w) => `${t(w.type)} ${w.value ?? ""}`).join(", ") : "—"}</dd>
        <dt>Ritirata</dt><dd>{s.retreat ?? "—"}</dd>
      </dl>
    </section>
  );
}

/** Se il catalogo non ha l'ID TCGplayer (carte nuove), lo prende da PokemonPriceTracker. */
function withTcgplayer(links: { name: string; url: string }[], graded: Graded | null) {
  if (links.some((l) => l.name === "TCGplayer") || !graded?.tcgplayer_id) return links;
  const tcg = { name: "TCGplayer", url: `https://www.tcgplayer.com/product/${graded.tcgplayer_id}` };
  return [links[0], tcg, ...links.slice(1)];
}

const ADD_LANGS = [...LANG_CHIPS, { code: "ko", label: "KOR", flag: "🇰🇷" }, { code: "zh", label: "CIN", flag: "🇨🇳" }];
const flagFor = (code: string) => ADD_LANGS.find((l) => l.code === code)?.flag ?? code.toUpperCase();

function OwnedPanel({ detail, onChanged }: {
  detail: CardDetail; onChanged: (owned: OwnedItem[], msg?: string) => void;
}) {
  const defaultLang = detail.catalog_lang === "ja" ? "ja" : detail.catalog_lang === "zh-tw" ? "zh" : "it";
  const [adding, setAdding] = useState(false);
  const [variant, setVariant] = useState(detail.variants[0]?.variant ?? "normal");
  const [lang, setLang] = useState(defaultLang);
  const [qty, setQty] = useState(1);
  const [cols, setCols] = useState<CollectionSummary[]>([]);
  const [colId, setColId] = useState<number | undefined>(undefined);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const owned = detail.owned ?? [];
  const label = (v: string) => detail.variants.find((x) => x.variant === v)?.label ?? v;

  useEffect(() => {
    if (adding && !cols.length) api.collections().then((r) => {
      setCols(r.collections);
      setColId(r.collections[0]?.id);
    }).catch(() => {});
  }, [adding]);

  const save = async (body: Parameters<typeof api.setItem>[0], msg: string) => {
    setBusy(true);
    setError(null);
    try {
      const r = await api.setItem(body);
      onChanged(r.owned, msg);
      setAdding(false);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  };

  const change = (o: OwnedItem, quantity: number) =>
    save({ collection_id: o.collection_id, card_id: o.card_id, catalog_lang: o.catalog_lang, variant: o.variant,
      lang: o.lang, quantity }, quantity ? "Quantità aggiornata" : "Tolta dalla collezione");

  const add = () => {
    const existing = owned.find((o) => o.variant === variant && o.lang === lang && (!colId || o.collection_id === colId));
    save({ collection_id: colId, card_id: detail.id, catalog_lang: detail.catalog_lang, variant, lang,
      quantity: (existing?.quantity ?? 0) + qty }, "✓ Aggiunta alla collezione");
  };

  const confirmMatch = async (o: OwnedItem) => {
    await api.confirmItem(o.id);
    onChanged(owned.map((x) => (x.id === o.id ? { ...x, needs_review: false } : x)), "Abbinamento confermato");
  };

  return (
    <section class="panel">
      <h2><Icon name="folder" size={20} /> Nella tua collezione</h2>
      {owned.length === 0 && !adding && <p class="muted">Non hai ancora questa carta.</p>}
      {owned.map((o) => (
        <div class="owned-row">
          <div class="owned-info">
            <div class="strong">{flagFor(o.lang)} {o.variant_label ?? label(o.variant)}</div>
            <div class="muted small">
              {o.collection_name}{o.unit_price !== null ? ` · ${price(o.unit_price)} cad.` : ""}
            </div>
            {o.variant_label && <div class="muted small">Prezzo della versione senza «{o.variant_label}»: non ha un prezzo separato.</div>}
            {o.needs_review && (
              <div class="review-box">
                Abbinata per nome durante l'import: è questa la carta giusta?
                <div class="row gap">
                  <button class="mini" onClick={() => confirmMatch(o)}>Sì, è giusta</button>
                  <button class="mini danger" onClick={() => change(o, 0)}>No, toglila</button>
                </div>
              </div>
            )}
          </div>
          <div class="stepper">
            <button onClick={() => change(o, o.quantity - 1)} disabled={busy} aria-label="Una in meno"><Icon name="minus" size={16} /></button>
            <span>{o.quantity}</span>
            <button onClick={() => change(o, o.quantity + 1)} disabled={busy} aria-label="Una in più"><Icon name="plus" size={16} /></button>
          </div>
        </div>
      ))}
      {!adding && <button class="btn ghost" onClick={() => setAdding(true)}><Icon name="plus" size={18} /> Aggiungi alla collezione</button>}
      {adding && (
        <>
          {detail.variants.length > 1 && (
            <div class="segmented flush">
              {detail.variants.map((v) => (
                <button class={v.variant === variant ? "on" : ""} onClick={() => setVariant(v.variant)}>{v.label}</button>
              ))}
            </div>
          )}
          <p class="muted">Lingua della tua carta</p>
          <div class="chips wrap">
            {ADD_LANGS.map((l) => (
              <button class={`chip ${lang === l.code ? "on" : ""}`} onClick={() => setLang(l.code)}>{l.flag} {l.label}</button>
            ))}
          </div>
          {cols.length > 1 && (
            <select class="input" value={colId} onChange={(e) => setColId(Number((e.target as HTMLSelectElement).value))}>
              {cols.map((c) => <option value={c.id}>{c.name}</option>)}
            </select>
          )}
          <div class="row gap">
            <div class="stepper">
              <button onClick={() => setQty(Math.max(1, qty - 1))} aria-label="Una in meno"><Icon name="minus" size={16} /></button>
              <span>{qty}</span>
              <button onClick={() => setQty(qty + 1)} aria-label="Una in più"><Icon name="plus" size={16} /></button>
            </div>
            <button class="btn primary grow" onClick={add} disabled={busy}>{busy ? "Salvo…" : "Aggiungi"}</button>
            <button class="btn ghost" onClick={() => setAdding(false)}>Annulla</button>
          </div>
          {error && <p class="error">{error}</p>}
        </>
      )}
    </section>
  );
}

const VERDICT_CLASS: Record<Analysis["verdict"], string> = {
  hold: "v-hold", neutral: "v-neutral", consider_selling: "v-consider", sell: "v-sell", low_value: "v-neutral",
};

function AnalysisPanel({ detail, variant }: { detail: CardDetail; variant: string }) {
  const [data, setData] = useState<Analysis | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const run = async () => {
    setBusy(true);
    setError(null);
    try {
      setData(await api.analysis(detail.catalog_lang, detail.id, variant));
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  };

  return (
    <section class="panel analysis">
      <h2><Icon name="chart" size={20} /> Tengo o vendo?</h2>
      {!data && !busy && (
        <>
          <p class="muted">Analizzo andamento del prezzo, storico, offerta, età e andamento del set e ti do una stima
            per i prossimi 30 giorni.</p>
          <button class="btn primary" onClick={run}>Analizza questa carta</button>
        </>
      )}
      {busy && <Spinner label="Analizzo il mercato…" />}
      {error && <p class="error">{error}</p>}
      {data && !data.available && <p class="muted">{data.reason}</p>}
      {data?.available && <AnalysisResult a={data} />}
    </section>
  );
}

function AnalysisResult({ a }: { a: Analysis }) {
  const down = Math.round(a.p_down * 100);
  return (
    <>
      <div class={`verdict ${VERDICT_CLASS[a.verdict]}`}>
        <div class="verdict-label">{a.verdict_label}</div>
        <p>{a.summary}</p>
      </div>

      <div class="prob">
        <div class="prob-head">
          <span class="down">↘ {down}% scende</span>
          <span class="up">{100 - down}% sale o resta ↗</span>
        </div>
        <div class="prob-bar"><div style={{ width: `${down}%` }} /></div>
        <p class="muted small">Probabilità stimata che fra {a.horizon_days} giorni valga meno di oggi ({price(a.price, a.currency)}).</p>
      </div>

      <div class="price-grid">
        <div><small>Fra 30 gg, da</small>{price(a.range_low, a.currency)}</div>
        <div><small>a</small>{price(a.range_high, a.currency)}</div>
        <div><small>Variazione attesa</small><span class={trendClass(a.expected_change * 100)}>{pct(a.expected_change * 100)}</span></div>
      </div>
      <p class="muted small">Affidabilità della stima: <b class={`conf conf-${a.confidence}`}>{a.confidence}</b>
        {a.priced_card ? ` · prezzi di ${a.priced_card}` : ""}{a.estimated_equivalent ? " (versione abbinata)" : ""}</p>

      <PriceChart a={a} />

      <h3 class="sub">Cosa ho considerato</h3>
      <ul class="signals">
        {a.signals.map((s) => (
          <li class={`sig sig-${s.direction}`}>
            <span class="sig-icon">{s.direction === "up" ? "↗" : s.direction === "down" ? "↘" : "→"}</span>
            <div><b>{s.title}</b><p>{s.detail}</p></div>
          </li>
        ))}
      </ul>

      {a.set && (
        <div class="set-box">
          <div class="strong">{a.set.name}: come va il set</div>
          <div class="row gap small">
            {a.set.change_30d !== null && <span class={`trend ${trendClass(a.set.change_30d * 100)}`}>{pct(a.set.change_30d * 100)} <small>30 giorni</small></span>}
            {a.set.change_7d !== null && <span class={`trend ${trendClass(a.set.change_7d * 100)}`}>{pct(a.set.change_7d * 100)} <small>7 giorni</small></span>}
          </div>
          <p class="muted small">Variazione della carta tipica, su {a.set.cards} carte del set che valgono almeno 0,50 €
            {a.set.share_up !== null ? `; in salita il ${Math.round(a.set.share_up * 100)}%` : ""}.</p>
          <Line points={a.set.index.map((p) => p.value)} />
        </div>
      )}

      <div class="notes">
        {a.notes.map((n) => <p>{n}</p>)}
        <p>{a.disclaimer}</p>
      </div>
    </>
  );
}

function PriceChart({ a }: { a: Analysis }) {
  if (a.history.length >= 2) {
    return (
      <div class="chart-box">
        <div class="chart-title">Prezzo registrato da PokeVault ({a.history.length} giorni)</div>
        <Line points={a.history.map((h) => h.price)} tall />
        <div class="chart-axis"><span>{date(a.history[0].day)}</span><span>{date(a.history[a.history.length - 1].day)}</span></div>
      </div>
    );
  }
  // Altezze relative tra minimo e massimo: le differenze di pochi euro devono vedersi.
  const vals = a.averages.map((x) => x.value);
  const lo = Math.min(...vals), hi = Math.max(...vals);
  const height = (v: number) => (hi - lo < 0.005 ? 70 : 25 + ((v - lo) / (hi - lo)) * 75);
  return (
    <div class="chart-box">
      <div class="chart-title">Ultimo mese su Cardmarket</div>
      <div class="bars">
        {a.averages.map((x) => (
          <div class="bar">
            <span class="bar-val">{price(x.value, a.currency)}</span>
            <div class="bar-fill" style={{ height: `${height(x.value)}%` }} />
            <span class="bar-label">{x.label}</span>
          </div>
        ))}
      </div>
      <p class="muted small">Lo storico giornaliero si accumula da stanotte per le carte in collezione e seguite.</p>
    </div>
  );
}

function Line({ points, tall = false }: { points: number[]; tall?: boolean }) {
  if (points.length < 2) return null;
  const w = 300, h = tall ? 90 : 44;
  const min = Math.min(...points), max = Math.max(...points);
  const span = max - min || 1;
  const d = points.map((p, i) => `${i ? "L" : "M"}${(i / (points.length - 1)) * w},${h - 4 - ((p - min) / span) * (h - 8)}`).join(" ");
  const up = points[points.length - 1] >= points[0];
  return (
    <svg class={`spark ${tall ? "tall" : ""}`} viewBox={`0 0 ${w} ${h}`} preserveAspectRatio="none" aria-hidden="true">
      <path d={d} fill="none" stroke={up ? "var(--up)" : "var(--down)"} stroke-width="2.5" stroke-linejoin="round" vector-effect="non-scaling-stroke" />
    </svg>
  );
}
