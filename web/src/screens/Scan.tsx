import { useEffect, useRef, useState } from "preact/hooks";
import { api, type CardSummary, type ScanResult } from "../api";
import { openCard } from "../nav";
import { CardGrid, CardImage, Header, Icon, Spinner } from "../ui";
import { searchFor } from "./Search";

// Riquadro guida (proporzioni di una carta, 63×88) al centro dell'inquadratura.
const GUIDE_W = 0.72;
const CARD_RATIO = 88 / 63;
const SAMPLE = 24;            // lato dell'immagine minuscola usata per capire se la carta è ferma
const STEADY_DIFF = 7;        // differenza media (0-255) sotto cui due fotogrammi sono "uguali"
const STEADY_FRAMES = 5;      // ~1,2 s fermi prima dello scatto automatico
const MOVED_DIFF = 22;        // dopo uno scatto, aspetto che la carta cambi davvero

type Scanned = { card: CardSummary; confident: boolean; at: number };

/** Ritaglia il riquadro guida dal video e lo rimpicciolisce (lato lungo 1600 px, JPEG). */
function grab(video: HTMLVideoElement): Promise<Blob> {
  const vw = video.videoWidth, vh = video.videoHeight;
  // Il video riempie il riquadro (object-fit: cover): ritaglio la parte centrale che corrisponde alla guida.
  let gw = vw * GUIDE_W, gh = gw * CARD_RATIO;
  if (gh > vh * 0.92) { gh = vh * 0.92; gw = gh / CARD_RATIO; }
  const sx = (vw - gw) / 2, sy = (vh - gh) / 2;
  const scale = Math.min(1, 1600 / gh);
  const canvas = document.createElement("canvas");
  canvas.width = Math.round(gw * scale);
  canvas.height = Math.round(gh * scale);
  canvas.getContext("2d")!.drawImage(video, sx, sy, gw, gh, 0, 0, canvas.width, canvas.height);
  return new Promise((resolve, reject) => canvas.toBlob((b) => (b ? resolve(b) : reject(new Error("foto"))), "image/jpeg", 0.88));
}

/** Rimpicciolisce una foto scelta dalla galleria (per chi non usa la fotocamera dal vivo). */
async function shrink(file: File): Promise<Blob> {
  const bitmap = await createImageBitmap(file);
  const scale = Math.min(1, 1600 / Math.max(bitmap.width, bitmap.height));
  const canvas = document.createElement("canvas");
  canvas.width = Math.round(bitmap.width * scale);
  canvas.height = Math.round(bitmap.height * scale);
  canvas.getContext("2d")!.drawImage(bitmap, 0, 0, canvas.width, canvas.height);
  return new Promise((resolve) => canvas.toBlob((b) => resolve(b ?? file), "image/jpeg", 0.88));
}

export function ScanScreen() {
  const video = useRef<HTMLVideoElement>(null);
  const stream = useRef<MediaStream | null>(null);
  const input = useRef<HTMLInputElement>(null);
  const [live, setLive] = useState(false);
  const [auto, setAuto] = useState(true);
  const [busy, setBusy] = useState(false);
  const [status, setStatus] = useState("Inquadra una carta nel riquadro");
  const [result, setResult] = useState<ScanResult | null>(null);
  const [scanned, setScanned] = useState<Scanned[]>([]);
  const [usage, setUsage] = useState<{ used: number; limit: number } | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [code, setCode] = useState("");
  const [added, setAdded] = useState<Record<string, boolean>>({});
  const busyRef = useRef(false);

  useEffect(() => {
    api.scanUsage().then((r) => setUsage(r.usage)).catch(() => {});
    return () => stop();
  }, []);

  const stop = () => {
    stream.current?.getTracks().forEach((t) => t.stop());
    stream.current = null;
    setLive(false);
  };

  const start = async () => {
    setError(null);
    try {
      const s = await navigator.mediaDevices.getUserMedia({
        video: { facingMode: { ideal: "environment" }, width: { ideal: 1920 }, height: { ideal: 1080 } }, audio: false,
      });
      stream.current = s;
      setLive(true);
      requestAnimationFrame(() => {
        if (video.current) {
          video.current.srcObject = s;
          video.current.play().catch(() => {});
        }
      });
    } catch {
      setError("Non riesco ad aprire la fotocamera: consenti l'accesso (Impostazioni → Safari/PokeVault → Fotocamera) " +
        "oppure scegli una foto dalla galleria.");
    }
  };

  const recognize = async (blob: Blob) => {
    busyRef.current = true;
    setBusy(true);
    setResult(null);
    setStatus("Leggo la carta…");
    try {
      const r = await api.scan(blob);
      if (r.usage) setUsage(r.usage);
      if (r.found && r.candidates.length) {
        const card = r.candidates[0];
        if (r.confident) {
          setScanned((list) => [{ card, confident: true, at: Date.now() }, ...list.filter((x) => x.card.id !== card.id)]);
          setStatus(`✓ ${card.name} ${card.number_label ?? ""}`);
          if (navigator.vibrate) navigator.vibrate(40);
        } else {
          setResult(r);
          setStatus("Non sono sicuro: scegli quella giusta qui sotto");
        }
      } else {
        setStatus(r.message ?? "Non ho riconosciuto la carta: avvicinati e riprova");
      }
      return r;
    } catch (e) {
      setStatus((e as Error).message);
      return null;
    } finally {
      busyRef.current = false;
      setBusy(false);
    }
  };

  // Scatto automatico: quando la carta resta ferma nel riquadro; poi aspetto che venga cambiata.
  useEffect(() => {
    if (!live || !auto) return;
    const canvas = document.createElement("canvas");
    canvas.width = canvas.height = SAMPLE;
    const ctx = canvas.getContext("2d", { willReadFrequently: true })!;
    let prev: Uint8ClampedArray | null = null;
    let lastShot: Uint8ClampedArray | null = null;
    let steady = 0;
    let armed = true;
    const timer = setInterval(async () => {
      const v = video.current;
      if (!v || v.readyState < 2 || busyRef.current) return;
      const vw = v.videoWidth, vh = v.videoHeight;
      const gw = vw * GUIDE_W * 0.8, gh = Math.min(gw * CARD_RATIO, vh * 0.8);
      ctx.drawImage(v, (vw - gw) / 2, (vh - gh) / 2, gw, gh, 0, 0, SAMPLE, SAMPLE);
      const px = ctx.getImageData(0, 0, SAMPLE, SAMPLE).data;
      const diff = (a: Uint8ClampedArray, b: Uint8ClampedArray) => {
        let d = 0;
        for (let i = 0; i < a.length; i += 4) d += Math.abs(a[i] - b[i]) + Math.abs(a[i + 1] - b[i + 1]);
        return d / (a.length / 2);
      };
      if (lastShot && !armed && diff(px, lastShot) > MOVED_DIFF) armed = true;  // carta cambiata
      steady = prev && diff(px, prev) < STEADY_DIFF ? steady + 1 : 0;
      prev = px.slice();
      if (armed && steady >= STEADY_FRAMES) {
        steady = 0;
        armed = false;
        lastShot = px.slice();
        await recognize(await grab(v));
      }
    }, 240);
    return () => clearInterval(timer);
  }, [live, auto]);

  const shoot = async () => {
    if (video.current && !busyRef.current) await recognize(await grab(video.current));
  };

  const onFile = async (e: Event) => {
    const file = (e.target as HTMLInputElement).files?.[0];
    (e.target as HTMLInputElement).value = "";
    if (!file) return;
    const r = await recognize(await shrink(file));
    if (r?.found && r.confident && r.candidates.length) openCard(r.candidates[0].catalog_lang, r.candidates[0].id);
  };

  const pick = (card: CardSummary) => {
    setScanned((list) => [{ card, confident: true, at: Date.now() }, ...list.filter((x) => x.card.id !== card.id)]);
    setResult(null);
    setStatus(`✓ ${card.name} ${card.number_label ?? ""}`);
  };

  // Aggiunta veloce alla collezione: prima variante della carta, lingua in base al catalogo.
  const quickAdd = async (card: CardSummary) => {
    const key = `${card.catalog_lang}:${card.id}`;
    try {
      const d = await api.card(card.catalog_lang, card.id);
      const variant = d.variants[0]?.variant ?? "normal";
      const lang = card.catalog_lang === "ja" ? "ja" : card.catalog_lang === "zh-tw" ? "zh" : "it";
      const have = d.owned.find((o) => o.variant === variant && o.lang === lang && o.kind !== "wishlist");
      await api.setItem({ card_id: card.id, catalog_lang: card.catalog_lang, variant, lang, quantity: (have?.quantity ?? 0) + 1 });
      setAdded((a) => ({ ...a, [key]: true }));
    } catch (e) {
      setStatus((e as Error).message);
    }
  };

  return (
    <>
      <Header title="Scansiona" right={live ? <button class="round" onClick={stop} aria-label="Chiudi fotocamera"><Icon name="close" /></button> : undefined} />
      <input ref={input} type="file" accept="image/*" hidden onChange={onFile} />

      {!live && (
        <div class="scan-box">
          <button class="scan-btn" onClick={start}>
            <Icon name="camera" size={44} />
            <span>Avvia lo scanner</span>
          </button>
          <p class="muted">Inquadra le carte una dopo l'altra: le riconosco da solo quando la carta è ferma nel riquadro.</p>
          <button class="btn ghost" onClick={() => input.current?.click()} disabled={busy}>Scegli una foto dalla galleria</button>
        </div>
      )}

      {live && (
        <div class="scanner">
          <video ref={video} playsInline muted autoPlay />
          <div class="scan-guide"><span /></div>
          <div class={`scan-status ${busy ? "busy" : ""}`}>{busy ? <><span class="dot" /> Leggo la carta…</> : status}</div>
          <div class="scan-controls">
            <button class={`chip ${auto ? "on" : ""}`} onClick={() => setAuto(!auto)}>{auto ? "Automatico" : "Manuale"}</button>
            <button class="shutter" onClick={shoot} disabled={busy} aria-label="Scatta" />
            <span class="scan-count">{scanned.length ? `${scanned.length} lette` : ""}</span>
          </div>
        </div>
      )}

      {error && <p class="error pad">{error}</p>}
      {usage && (
        <p class="muted small pad">Letture di foto questo mese: {usage.used} su {usage.limit} (gratis fino a 1.000).</p>
      )}
      {busy && !live && <Spinner />}

      {result && result.candidates.length > 0 && (
        <div>
          <h2 class="section">Quale di queste?</h2>
          {live
            ? <div class="cand-row">{result.candidates.map((c) => (
                <button class="cand" onClick={() => pick(c)}><CardImage src={c.image} alt={c.name} /><span>{c.name} {c.number_label}</span></button>
              ))}</div>
            : <CardGrid cards={result.candidates} />}
        </div>
      )}

      {scanned.length > 0 && (
        <>
          <h2 class="section">Carte lette</h2>
          <div class="list">
            {scanned.map(({ card }) => {
              const key = `${card.catalog_lang}:${card.id}`;
              return (
                <div class="list-row">
                  <button class="row gap grow" onClick={() => { stop(); openCard(card.catalog_lang, card.id); }}>
                    <CardImage src={card.image} alt={card.name} class="thumb" />
                    <div class="list-main">
                      <div class="strong">{card.name}</div>
                      <div class="muted small">{card.set_name} {card.number_label}</div>
                    </div>
                  </button>
                  <button class={`mini ${added[key] ? "" : "gold"}`} onClick={() => quickAdd(card)} disabled={added[key]}>
                    {added[key] ? "✓ Aggiunta" : <><Icon name="plus" size={14} /> Collezione</>}
                  </button>
                </div>
              );
            })}
          </div>
        </>
      )}

      <form class="code-form" onSubmit={(e) => { e.preventDefault(); if (code.trim()) searchFor(code.trim()); }}>
        <p class="muted">Oppure scrivi codice e numero stampati in basso a sinistra:</p>
        <div class="row gap">
          <input class="input" placeholder="es. 30C 154 o MEW 006" value={code}
            onInput={(e) => setCode((e.target as HTMLInputElement).value)} autoCapitalize="characters" />
          <button class="btn primary" type="submit">Cerca</button>
        </div>
      </form>
    </>
  );
}
