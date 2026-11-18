import { useEffect, useState } from "preact/hooks";
import { api, type CardDetail, type Graded, type PriceGroup, type TrackingInfo } from "../api";
import { date, LANG_CHIPS, pct, plural, price, STAGE_IT, trendClass, TYPE_IT } from "../format";
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
            <div class="hero"><CardImage src={detail.image} alt={detail.name} class="big" /></div>

            <div class="card-meta">
              <div class="row gap">
                <span class="number">#{detail.number}{detail.set.official ? <small> / {detail.set.official}</small> : null}</span>
                {detail.rarity && <span class="pill">{detail.rarity}</span>}
              </div>
              {detail.illustrator && (
                <button class="link-row" onClick={() => searchFor(detail.illustrator!)}>
                  <Icon name="brush" size={18} /> <u>{detail.illustrator}</u>
                </button>
              )}
              {detail.dex_ids.map((n) => (
                <button class="link-row" onClick={() => searchFor(`#${n}`)}>
                  <span class="dex">#{String(n).padStart(4, "0")}</span> <u>tutte le carte di questo Pokémon</u>
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
              <h2>Prezzi {variant && detail.variants.length === 1 ? <small>· {variant.label}</small> : null}</h2>
              {variant?.groups.map((g) => <PriceBlock group={g} />)}
              <PriceNotes groups={variant?.groups ?? []} />
            </section>

            <GradedPanel graded={graded} />

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
                {detail.set.logo && <img class="set-logo" src={detail.set.logo} alt="" loading="lazy" />}
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
                  <a class="btn ghost" href={m.url} target="_blank" rel="noopener noreferrer">{m.name} <Icon name="link" size={16} /></a>
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
  return (
    <div class="price-block">
      <div class="price-head">
        <span>{group.label}</span>
        {group.estimated && group.card_label && <small class="muted">{group.card_label.split(" · ")[1]}</small>}
      </div>
      {cm ? (
        <>
          <div class="price-main">{price(cm.trend ?? cm.avg7 ?? cm.avg, cm.currency)}<small>prezzo di mercato</small></div>
          <div class="price-sub">da {price(cm.low, cm.currency)} · media vendite {price(cm.avg, cm.currency)}</div>
          <div class="price-trend">
            <span class={trendClass(cm.change_7d)}>{pct(cm.change_7d)} <small>vs media 7 gg</small></span>
            <span class={trendClass(cm.change_30d)}>{pct(cm.change_30d)} <small>vs media 30 gg</small></span>
          </div>
        </>
      ) : (
        <p class="muted">{group.notes[0] ?? "Nessun prezzo su Cardmarket per questa versione."}</p>
      )}
      {tp && <div class="price-sub">🇺🇸 TCGplayer: {price(tp.market, tp.currency)} · da {price(tp.low, tp.currency)}</div>}
    </div>
  );
}

function PriceNotes({ groups }: { groups: PriceGroup[] }) {
  const updated = groups.map((g) => g.cardmarket?.updated).filter(Boolean).sort().pop();
  return (
    <div class="notes">
      {groups.some((g) => g.aggregated) && (
        <p>Cardmarket non distingue italiano, inglese, tedesco, francese, spagnolo e portoghese: il prezzo è lo stesso.</p>
      )}
      {groups.some((g) => g.estimated) && <p>La versione in un'altra lingua è abbinata in automatico (stessa illustrazione).</p>}
      {updated && <p>Prezzi Cardmarket del {date(updated, true)}.</p>}
    </div>
  );
}

function GradedPanel({ graded }: { graded: Graded | null }) {
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
                <div class="grade-sub">{[g.price_eur !== null ? price(g.price_usd, "USD") : null,
                  plural(g.sales, "vendita", "vendite")].filter(Boolean).join(" · ")}
                  {g.trend === "up" ? " ↗" : g.trend === "down" ? " ↘" : ""}</div>
              </div>
            ))}
          </div>
          <p class="notes">Stampa {graded.print}: vendite eBay e Fanatics negli USA.
            {graded.usd_per_eur ? ` Convertite in euro al cambio BCE del ${date(graded.fx_date)} (1 € = ${graded.usd_per_eur.toLocaleString("it-IT")} $).` : ""}</p>
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
