import { useEffect, useState } from "preact/hooks";
import { api, type CollectionItem, type Friend, type FriendItem, type Trade, type TradeCard } from "../api";
import { date, LANG_CHIPS, plural, price } from "../format";
import { go, openCard } from "../nav";
import { CardImage, Header, Icon, Spinner } from "../ui";

const flag = (code: string) => LANG_CHIPS.find((l) => l.code === code)?.flag ?? "";
const STATUS: Record<Trade["status"], string> = {
  proposed: "In attesa di risposta", accepted: "Accettato: scambiatevi le carte", rejected: "Rifiutato",
  cancelled: "Annullato", countered: "Sostituito da una controproposta", completed: "Completato", undone: "Annullato dopo il completamento",
};

/** Condivide (o copia) il link di invito. */
export async function shareInvite(): Promise<string> {
  const inv = await api.createInvite();
  const url = `${location.origin}${inv.path}`;
  const text = "Ti invito su PokeVault: vediamo le nostre collezioni di carte Pokémon e facciamo scambi.";
  try {
    if (navigator.share) {
      await navigator.share({ title: "PokeVault", text, url });
      return "Invito pronto: valido 7 giorni, per una persona.";
    }
  } catch {
    /* condivisione annullata: copio */
  }
  await navigator.clipboard.writeText(url).catch(() => {});
  return `Link copiato: ${url}`;
}

export function FriendsScreen({ route }: { route: string[] }) {
  return route.length >= 2 ? <FriendView id={Number(route[1])} /> : <FriendsHome />;
}

function FriendsHome() {
  const [friends, setFriends] = useState<Friend[] | null>(null);
  const [trades, setTrades] = useState<Trade[]>([]);
  const [open, setOpen] = useState<Trade | null>(null);
  const [msg, setMsg] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const load = () => {
    api.friends().then((r) => setFriends(r.friends)).catch((e) => setError((e as Error).message));
    api.trades().then((r) => setTrades(r.trades)).catch(() => {});
  };
  useEffect(load, []);

  const invite = async () => {
    try { setMsg(await shareInvite()); } catch (e) { setMsg((e as Error).message); }
  };
  const active = trades.filter((t) => t.status === "proposed" || t.status === "accepted");
  const past = trades.filter((t) => !active.includes(t)).slice(0, 15);

  return (
    <>
      <Header title="Amici" right={<button class="round" onClick={invite} aria-label="Invita un amico"><Icon name="plus" /></button>} />
      {msg && <p class="banner">{msg}</p>}
      {error && <p class="error pad">{error}</p>}
      {!friends && !error && <Spinner />}

      {active.length > 0 && (
        <>
          <h2 class="section">Scambi in corso</h2>
          <div class="list">{active.map((t) => <TradeRow t={t} onOpen={() => setOpen(t)} />)}</div>
        </>
      )}

      {friends && friends.length === 0 && (
        <div class="empty">
          <Icon name="users" size={44} />
          <h2>Invita i tuoi amici</h2>
          <p class="muted">Ricevono un link: scelgono nome e PIN, mettono l'app sulla Home e importano la loro collezione.
            Poi vedete le collezioni l'uno dell'altro e vi proponete scambi.</p>
          <button class="btn primary" onClick={invite}><Icon name="plus" size={18} /> Invita un amico</button>
        </div>
      )}
      {friends && friends.length > 0 && (
        <>
          <h2 class="section">I tuoi amici</h2>
          <div class="list">
            {friends.map((f) => (
              <button class="list-row" onClick={() => go(`friends/${f.id}`)}>
                <span class="avatar">{f.name.slice(0, 1).toUpperCase()}</span>
                <div class="list-main">
                  <div class="strong">{f.name}</div>
                  <div class="muted small">{plural(f.cards, "carta", "carte")} · {plural(f.unique, "diversa", "diverse")}</div>
                  {(f.they_have > 0 || f.you_have > 0) && (
                    <div class="target-list">
                      {f.they_have > 0 && <span class="target"><span class="target-tag">❤</span>{f.they_have} che cerchi</span>}
                      {f.you_have > 0 && <span class="target"><span class="target-tag">↔</span>{f.you_have} che cerca</span>}
                    </div>
                  )}
                </div>
                <Icon name="chevron" size={18} />
              </button>
            ))}
          </div>
        </>
      )}

      {past.length > 0 && (
        <>
          <h2 class="section">Scambi passati</h2>
          <div class="list">{past.map((t) => <TradeRow t={t} onOpen={() => setOpen(t)} />)}</div>
        </>
      )}
      {open && <TradeSheet trade={open} onClose={() => { setOpen(null); load(); }} onChanged={(t) => { setOpen(t); load(); }} />}
    </>
  );
}

function TradeRow({ t, onOpen }: { t: Trade; onOpen: () => void }) {
  const title = t.role === "proposer" ? `A ${t.other.name}` : `Da ${t.other.name}`;
  return (
    <button class={`list-row ${t.needs_me ? "needs-me" : ""}`} onClick={onOpen}>
      <div class="trade-thumbs">
        {[...t.give, ...t.take].slice(0, 3).map((c) => <CardImage src={c.image} alt={c.name} class="thumb" />)}
      </div>
      <div class="list-main">
        <div class="strong">{title}{t.needs_me ? " · tocca a te" : ""}</div>
        <div class="muted small">Dai {plural(t.give.reduce((s, c) => s + c.quantity, 0), "carta", "carte")} · ricevi {plural(t.take.reduce((s, c) => s + c.quantity, 0), "carta", "carte")}</div>
        <div class="muted small">{STATUS[t.status]} · {date(t.updated_at)}</div>
      </div>
      <Icon name="chevron" size={18} />
    </button>
  );
}

// --- profilo dell'amico ---------------------------------------------------------------------------------------

type Pick = { item: CollectionItem; qty: number };

function FriendView({ id }: { id: number }) {
  const [friend, setFriend] = useState<Friend | null>(null);
  const [tab, setTab] = useState<string>("matches");
  const [matches, setMatches] = useState<{ they_have: CollectionItem[]; you_have: CollectionItem[] } | null>(null);
  const [col, setCol] = useState<{ name: string; show_values: boolean; value?: number; items: FriendItem[] } | null>(null);
  const [picking, setPicking] = useState(false);
  const [take, setTake] = useState<Record<number, Pick>>({});
  const [give, setGive] = useState<Record<number, Pick>>({});
  const [composer, setComposer] = useState(false);
  const [q, setQ] = useState("");

  useEffect(() => {
    api.friends().then((r) => setFriend(r.friends.find((f) => f.id === id) ?? null));
    api.matches(id).then(setMatches).catch(() => setMatches({ they_have: [], you_have: [] }));
  }, [id]);
  useEffect(() => {
    setCol(null);
    if (tab !== "matches") api.friendCollection(id, Number(tab)).then(setCol).catch(() => setCol(null));
  }, [tab, id]);

  const toggle = (map: Record<number, Pick>, set: (m: Record<number, Pick>) => void, item: CollectionItem) => {
    const next = { ...map };
    if (next[item.id]) delete next[item.id];
    else next[item.id] = { item, qty: 1 };
    set(next);
  };
  const tileClick = (item: CollectionItem, mine: boolean) => {
    if (!picking) return openCard(item.catalog_lang, item.card_id);
    mine ? toggle(give, setGive, item) : toggle(take, setTake, item);
  };
  const selected = Object.keys(take).length + Object.keys(give).length;

  const grid = (items: (CollectionItem & { i_have?: boolean; i_want?: boolean })[], mine: boolean, values = true) => (
    <div class="grid">
      {items.filter((i) => !q || `${i.name} ${i.set_name ?? ""}`.toLowerCase().includes(q.toLowerCase())).map((i) => {
        const on = mine ? give[i.id] : take[i.id];
        return (
          <button class={`tile ${on ? "picked" : ""}`} onClick={() => tileClick(i, mine)}>
            <div class="tile-img">
              <CardImage src={i.image} alt={i.name} />
              {i.quantity > 1 && <span class="qty">×{i.quantity}</span>}
              {i.i_want && <span class="flag-want">❤</span>}
              {i.i_have && <span class="owned-badge">✓</span>}
              {on && <span class="pick-check">✓</span>}
            </div>
            <span class="tile-name">{i.name}</span>
            <span class="tile-sub">{flag(i.lang)} {i.number_label ?? ""} · {i.set_name ?? ""}</span>
            {values && i.unit_price !== null && <span class="tile-price">{price(i.unit_price)}</span>}
          </button>
        );
      })}
    </div>
  );

  if (!friend) return <Spinner />;
  return (
    <>
      <div class="screen-head">
        <button class="round" onClick={() => go("friends")} aria-label="Indietro"><Icon name="back" /></button>
        <h1 class="friend-title"><span class="avatar big">{friend.name.slice(0, 1).toUpperCase()}</span>{friend.name}</h1>
        <span />
      </div>
      <div class="chips">
        <button class={`chip ${tab === "matches" ? "on" : ""}`} onClick={() => setTab("matches")}>↔ Scambi possibili</button>
        {friend.collections.map((c) => (
          <button class={`chip ${tab === String(c.id) ? "on" : ""}`} onClick={() => setTab(String(c.id))}>
            {c.kind === "wishlist" ? "❤ " : ""}{c.name} ({c.cards})
          </button>
        ))}
      </div>
      <div class="row gap pad trade-bar-top">
        <button class={`btn ${picking ? "ghost" : "primary"} grow`} onClick={() => setPicking(!picking)}>
          {picking ? "Fine selezione" : "Proponi uno scambio"}
        </button>
      </div>
      {picking && <p class="muted small pad">Tocca le carte di {friend.name} che vuoi e, in "Scambi possibili", le tue da dare.</p>}
      <div class="searchbar small">
        <Icon name="search" size={18} />
        <input type="search" placeholder="Cerca tra le carte" value={q} onInput={(e) => setQ((e.target as HTMLInputElement).value)} />
      </div>

      {tab === "matches" && !matches && <Spinner />}
      {tab === "matches" && matches && (
        <>
          <h2 class="section">❤ Ha carte che cerchi</h2>
          {matches.they_have.length === 0
            ? <p class="muted pad">Nessuna carta della tua lista desideri: aggiungine dalla scheda di una carta (❤).</p>
            : grid(matches.they_have, false)}
          <h2 class="section">↔ Cerca carte che hai</h2>
          {matches.you_have.length === 0
            ? <p class="muted pad">Nella sua lista desideri non c'è nessuna delle tue carte.</p>
            : grid(matches.you_have, true)}
        </>
      )}
      {tab !== "matches" && !col && <Spinner />}
      {tab !== "matches" && col && (
        <>
          <p class="muted small pad">{plural(col.items.reduce((s, i) => s + i.quantity, 0), "carta", "carte")}
            {col.show_values && col.value !== undefined ? ` · valore ${price(col.value)}` : " · valori nascosti"}
            {" · ❤ = la cerchi, ✓ = ce l'hai già"}</p>
          {grid(col.items, false, col.show_values)}
        </>
      )}

      {selected > 0 && (
        <div class="pick-bar">
          <span>{plural(selected, "carta scelta", "carte scelte")}</span>
          <button class="btn primary" onClick={() => setComposer(true)}>Continua</button>
        </div>
      )}
      {composer && (
        <TradeComposer friend={friend} initialTake={take} initialGive={give}
          onClose={() => setComposer(false)} onSent={() => { setComposer(false); setTake({}); setGive({}); setPicking(false); go("friends"); }} />
      )}
    </>
  );
}

// --- composizione della proposta ------------------------------------------------------------------------------

function TradeComposer({ friend, initialTake, initialGive, parentId, onClose, onSent }: {
  friend: { id: number; name: string }; initialTake: Record<number, Pick>; initialGive: Record<number, Pick>;
  parentId?: number; onClose: () => void; onSent: () => void;
}) {
  const [take, setTake] = useState(initialTake);
  const [give, setGive] = useState(initialGive);
  const [all, setAll] = useState<{ theirs: CollectionItem[]; mine: CollectionItem[] } | null>(null);
  const [adding, setAdding] = useState<"take" | "give" | null>(null);
  const [message, setMessage] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [q, setQ] = useState("");

  useEffect(() => { api.tradeable(friend.id).then(setAll).catch(() => {}); }, [friend.id]);

  const value = (m: Record<number, Pick>) => Object.values(m).reduce((s, p) => s + (p.item.unit_price ?? 0) * p.qty, 0);
  const tv = value(take), gv = value(give);
  const diff = gv - tv;

  const setQty = (m: Record<number, Pick>, set: (x: Record<number, Pick>) => void, id: number, qty: number) => {
    const next = { ...m };
    if (qty <= 0) delete next[id];
    else next[id] = { ...next[id], qty: Math.min(qty, next[id].item.quantity) };
    set(next);
  };

  const send = async () => {
    setBusy(true);
    setError(null);
    try {
      await api.propose({
        friend_id: friend.id, message: message.trim() || undefined, parent_id: parentId,
        give: Object.values(give).map((p) => ({ item_id: p.item.id, quantity: p.qty })),
        take: Object.values(take).map((p) => ({ item_id: p.item.id, quantity: p.qty })),
      });
      onSent();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  };

  const side = (label: string, m: Record<number, Pick>, set: (x: Record<number, Pick>) => void, key: "take" | "give") => (
    <>
      <h3>{label} <small class="muted">{price(value(m))}</small></h3>
      {Object.values(m).length === 0 && <p class="muted small">Nessuna carta.</p>}
      {Object.values(m).map((p) => (
        <div class="owned-row">
          <CardImage src={p.item.image} alt={p.item.name} class="thumb" />
          <div class="owned-info">
            <div class="strong">{p.item.name}</div>
            <div class="muted small">{flag(p.item.lang)} {p.item.number_label} · {p.item.unit_price !== null ? `${price(p.item.unit_price)} cad.` : "prezzo n.d."}</div>
          </div>
          <div class="stepper">
            <button onClick={() => setQty(m, set, p.item.id, p.qty - 1)} aria-label="Una in meno"><Icon name="minus" size={16} /></button>
            <span>{p.qty}</span>
            <button onClick={() => setQty(m, set, p.item.id, p.qty + 1)} aria-label="Una in più"><Icon name="plus" size={16} /></button>
          </div>
        </div>
      ))}
      <button class="mini" onClick={() => { setAdding(key); setQ(""); }}><Icon name="plus" size={14} /> Aggiungi</button>
    </>
  );

  const pool = adding === "take" ? all?.theirs : all?.mine;
  const chosen = adding === "take" ? take : give;
  return (
    <div class="modal" onClick={onClose}>
      <div class="modal-card" onClick={(e) => e.stopPropagation()}>
        <h2>{parentId ? "Controproposta" : "Proposta"} a {friend.name}</h2>
        {!adding && (
          <>
            {side(`Ricevi da ${friend.name}`, take, setTake, "take")}
            {side("Dai tu", give, setGive, "give")}
            <div class="balance">
              <span>Dai {price(gv)}</span><span>Ricevi {price(tv)}</span>
            </div>
            <p class={`small ${Math.abs(diff) < 1 ? "up" : "muted"}`}>
              {Math.abs(diff) < 1 ? "Scambio equilibrato." : diff > 0 ? `Dai ${price(diff)} in più (prezzi Cardmarket).` : `Ricevi ${price(-diff)} in più (prezzi Cardmarket).`}
            </p>
            <textarea class="input area" placeholder="Messaggio (facoltativo)" maxLength={500} value={message}
              onInput={(e) => setMessage((e.target as HTMLTextAreaElement).value)} />
            {error && <p class="error">{error}</p>}
            <div class="row gap">
              <button class="btn primary grow" onClick={send} disabled={busy || (!Object.keys(take).length && !Object.keys(give).length)}>
                {busy ? "Invio…" : "Invia la proposta"}
              </button>
              <button class="btn ghost" onClick={onClose}>Annulla</button>
            </div>
          </>
        )}
        {adding && (
          <>
            <p class="muted small">{adding === "take" ? `Carte visibili di ${friend.name}` : "Le tue carte (prima i doppioni)"}</p>
            <input class="input" placeholder="Cerca" value={q} onInput={(e) => setQ((e.target as HTMLInputElement).value)} />
            {!pool && <Spinner />}
            <div class="pick-list">
              {(pool ?? []).filter((i) => !q || i.name.toLowerCase().includes(q.toLowerCase())).slice(0, 80).map((i) => (
                <button class={`owned-row ${chosen[i.id] ? "picked" : ""}`} onClick={() => {
                  const next = { ...chosen };
                  if (next[i.id]) delete next[i.id]; else next[i.id] = { item: i, qty: 1 };
                  adding === "take" ? setTake(next) : setGive(next);
                }}>
                  <CardImage src={i.image} alt={i.name} class="thumb" />
                  <div class="owned-info">
                    <div class="strong">{i.name}{i.quantity > 1 ? ` ×${i.quantity}` : ""}</div>
                    <div class="muted small">{flag(i.lang)} {i.number_label} · {i.set_name}</div>
                  </div>
                  <span class="pick-dot">{chosen[i.id] ? "✓" : "+"}</span>
                </button>
              ))}
            </div>
            <button class="btn primary" onClick={() => setAdding(null)}>Fatto</button>
          </>
        )}
      </div>
    </div>
  );
}

// --- dettaglio di uno scambio -----------------------------------------------------------------------------------

export function TradeSheet({ trade, onClose, onChanged }: { trade: Trade; onClose: () => void; onChanged: (t: Trade) => void }) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [counter, setCounter] = useState(false);

  const run = async (action: string, ask?: string) => {
    if (ask && !confirm(ask)) return;
    setBusy(true);
    setError(null);
    try {
      onChanged((await api.tradeAction(trade.id, action)).trade);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  };

  const list = (cards: TradeCard[]) => cards.length === 0 ? <p class="muted small">Nessuna carta.</p> : cards.map((c) => (
    <button class="owned-row" onClick={() => openCard(c.catalog_lang, c.card_id)}>
      <CardImage src={c.image} alt={c.name} class="thumb" />
      <div class="owned-info">
        <div class="strong">{c.name}{c.quantity > 1 ? ` ×${c.quantity}` : ""}</div>
        <div class="muted small">{flag(c.lang)} {c.number_label} · {c.set_name}</div>
      </div>
      <span class="small">{c.total !== null ? price(c.total) : "—"}</span>
    </button>
  ));

  return (
    <div class="modal" onClick={onClose}>
      <div class="modal-card" onClick={(e) => e.stopPropagation()}>
        <h2>Scambio con {trade.other.name}</h2>
        <p class="pill gold">{STATUS[trade.status]}</p>
        {trade.message && <p class="quote">“{trade.message}”</p>}
        <h3>Dai tu <small class="muted">{price(trade.give_value)}</small></h3>
        {list(trade.give)}
        <h3>Ricevi <small class="muted">{price(trade.take_value)}</small></h3>
        {list(trade.take)}
        {error && <p class="error">{error}</p>}

        {trade.status === "proposed" && trade.role === "recipient" && (
          <div class="row gap">
            <button class="btn primary grow" disabled={busy} onClick={() => run("accept")}>Accetta</button>
            <button class="btn ghost" disabled={busy} onClick={() => setCounter(true)}>Controproposta</button>
            <button class="btn danger" disabled={busy} onClick={() => run("reject", "Rifiutare la proposta?")}>Rifiuta</button>
          </div>
        )}
        {trade.status === "proposed" && trade.role === "proposer" && (
          <button class="btn danger" disabled={busy} onClick={() => run("cancel", "Ritirare la proposta?")}>Ritira la proposta</button>
        )}
        {trade.status === "accepted" && (
          <>
            <p class="muted small">Scambiatevi le carte di persona o per posta. Quando le hai ricevute, conferma: appena
              confermate entrambi, le carte passano da sole nelle vostre collezioni.</p>
            {trade.i_confirmed
              ? <p class="pill">Hai confermato · {trade.they_confirmed ? "completato" : `in attesa di ${trade.other.name}`}</p>
              : <button class="btn primary" disabled={busy} onClick={() => run("confirm")}>Ho ricevuto le carte</button>}
            <button class="btn danger" disabled={busy} onClick={() => run("cancel", "Annullare lo scambio?")}>Annulla lo scambio</button>
          </>
        )}
        {trade.can_undo && (
          <button class="btn ghost" disabled={busy}
            onClick={() => run("undo", "Annullare lo scambio completato? Le carte tornano nelle collezioni di prima.")}>
            Annulla lo scambio (le carte tornano com'erano)
          </button>
        )}
        <button class="btn primary" onClick={onClose}>Chiudi</button>
      </div>
      {counter && (
        <TradeComposer friend={trade.other} initialTake={{}} initialGive={{}}
          parentId={trade.id} onClose={() => setCounter(false)} onSent={() => { setCounter(false); onClose(); }} />
      )}
    </div>
  );
}
