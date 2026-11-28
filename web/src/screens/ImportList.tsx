import { useState } from "preact/hooks";
import { api, type ChecklistPreview, type ChecklistResult, type CollectionSummary } from "../api";
import { LANG_CHIPS, plural } from "../format";
import { openCard } from "../nav";
import { Icon, Spinner } from "../ui";

/** Scelta del tipo di import: file di MyDex o lista incollata (es. "Carte che mi mancano" di Pullaxy). */
export function ImportChooser({ onFile, onList, onClose }: { onFile: () => void; onList: () => void; onClose: () => void }) {
  return (
    <div class="modal" onClick={onClose}>
      <div class="modal-card" onClick={(e) => e.stopPropagation()}>
        <h2>Importa</h2>
        <button class="btn primary" onClick={onList}><Icon name="plus" size={18} /> Incolla una lista di carte</button>
        <p class="muted small">Ad esempio «Carte che mi mancano» o «Carte che ho» di Pullaxy: una carta per riga, che inizia con #.</p>
        <button class="btn" onClick={onFile}><Icon name="upload" size={18} /> File di MyDex (.json)</button>
        <button class="btn ghost" onClick={onClose}>Annulla</button>
      </div>
    </div>
  );
}

export function ChecklistImport({ collections, onDone, onClose }: {
  collections: CollectionSummary[];
  onDone: (r: ChecklistResult) => void;
  onClose: () => void;
}) {
  const own = collections.filter((c) => c.kind !== "wishlist");
  const [text, setText] = useState("");
  const [preview, setPreview] = useState<ChecklistPreview | null>(null);
  const [wish, setWish] = useState(true);
  const [mine, setMine] = useState(true);
  const [lang, setLang] = useState("it");
  const [target, setTarget] = useState<number | undefined>(own[0]?.id);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const paste = async () => {
    try { setText(await navigator.clipboard.readText()); } catch { setError("Non riesco a leggere gli appunti: incolla la lista nel riquadro."); }
  };

  const check = async () => {
    setBusy(true);
    setError(null);
    try {
      const p = await api.checklistPreview(text);
      setPreview(p);
      setLang(p.lang);
    } catch (e) { setError((e as Error).message); } finally { setBusy(false); }
  };

  const run = async () => {
    setBusy(true);
    setError(null);
    try {
      onDone(await api.checklistImport({ text, wish, own: mine, lang, collection_id: target }));
    } catch (e) { setError((e as Error).message); setBusy(false); }
  };

  const missing = preview?.kind !== "owned";
  const wishCount = preview ? (missing ? preview.listed - preview.listed_have : preview.rest - preview.rest_have) : 0;
  const ownCount = preview ? (missing ? preview.rest - preview.rest_have : preview.listed - preview.listed_have) : 0;
  const have = preview ? preview.listed_have + preview.rest_have : 0;

  return (
    <div class="modal" onClick={busy ? undefined : onClose}>
      <div class="modal-card" onClick={(e) => e.stopPropagation()}>
        {!preview && (
          <>
            <h2>Incolla la lista</h2>
            <textarea class="input area wide list-area" placeholder={"Carte che mi mancano · 30th Celebration\n#001 Exeggcute\n#BS 4 Charizard\n…"}
              value={text} onInput={(e) => setText((e.target as HTMLTextAreaElement).value)} />
            <div class="row gap">
              <button class="btn" onClick={paste}>Incolla dagli appunti</button>
              <button class="btn primary grow" onClick={check} disabled={busy || !text.trim()}>Controlla</button>
            </div>
          </>
        )}
        {preview && (
          <>
            <h2>{preview.set_name}</h2>
            <p class="muted small">
              {missing ? "Lista delle carte che ti mancano" : "Lista delle carte che hai"}
              {preview.sets.length > 1 && <> · con {preview.sets.slice(1).map((s) => s.name).join(", ")}</>}
            </p>
            <label class="switch"><input type="checkbox" checked={wish} onChange={() => setWish(!wish)} />
              <span>❤ Metti nella lista desideri <b>{plural(wishCount, "carta che ti manca", "carte che ti mancano")}</b></span></label>
            <label class="switch"><input type="checkbox" checked={mine} onChange={() => setMine(!mine)} />
              <span>✓ Segna come tue <b>{plural(ownCount, "carta", "carte")}</b> (1 copia)</span></label>
            {mine && (
              <div class="row gap">
                <select class="input" value={lang} onChange={(e) => setLang((e.target as HTMLSelectElement).value)} aria-label="Lingua">
                  {LANG_CHIPS.map((l) => <option value={l.code}>{l.flag} {l.label}</option>)}
                </select>
                {own.length > 1 && (
                  <select class="input" value={target} onChange={(e) => setTarget(Number((e.target as HTMLSelectElement).value))} aria-label="Collezione">
                    {own.map((c) => <option value={c.id}>{c.name}</option>)}
                  </select>
                )}
              </div>
            )}
            {have > 0 && <p class="muted small">{plural(have, "carta è", "carte sono")} già nella tua collezione: restano come sono.</p>}
            {preview.review.length > 0 && (
              <>
                <h3>Da verificare ({preview.review.length})</h3>
                <p class="muted small">Il numero non corrispondeva: le ho abbinate per nome.</p>
                <ul class="report-list">
                  {preview.review.map((r) => (
                    <li><button class="link" onClick={() => openCard("en", r.card_id)}>{r.line} → {r.name} · {r.set_name}</button></li>
                  ))}
                </ul>
              </>
            )}
            {preview.unmatched.length > 0 && (
              <>
                <h3>Non trovate ({preview.unmatched.length})</h3>
                <ul class="report-list">
                  {preview.unmatched.map((u) => <li>{u.line}<br /><small class="muted">{u.reason}</small></li>)}
                </ul>
              </>
            )}
            <div class="row gap">
              <button class="btn ghost" onClick={() => setPreview(null)} disabled={busy}>Indietro</button>
              <button class="btn primary grow" onClick={run} disabled={busy || (!wish && !mine)}>Importa</button>
            </div>
          </>
        )}
        {busy && <Spinner />}
        {error && <p class="error">{error}</p>}
      </div>
    </div>
  );
}
