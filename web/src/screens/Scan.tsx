import { useRef, useState } from "preact/hooks";
import { api, type ScanResult } from "../api";
import { openCard } from "../nav";
import { CardGrid, Header, Icon, Spinner } from "../ui";
import { searchFor } from "./Search";

/** Rimpicciolisce la foto (lato lungo 1600 px, JPEG): upload veloce e testo ancora ben leggibile. */
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
  const input = useRef<HTMLInputElement>(null);
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState<ScanResult | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [code, setCode] = useState("");

  const onFile = async (e: Event) => {
    const file = (e.target as HTMLInputElement).files?.[0];
    (e.target as HTMLInputElement).value = "";
    if (!file) return;
    setBusy(true);
    setError(null);
    setResult(null);
    try {
      const r = await api.scan(await shrink(file));
      if (r.found && r.confident && r.candidates.length) {
        openCard(r.candidates[0].catalog_lang, r.candidates[0].id);
      } else {
        setResult(r);
      }
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(false);
    }
  };

  return (
    <>
      <Header title="Scansiona" />
      <input ref={input} type="file" accept="image/*" capture="environment" hidden onChange={onFile} />
      <div class="scan-box">
        <button class="scan-btn" onClick={() => input.current?.click()} disabled={busy}>
          <Icon name="camera" size={44} />
          <span>{busy ? "Leggo la carta…" : "Fotografa una carta"}</span>
        </button>
        <p class="muted">Carta dritta, ben illuminata e senza riflessi: nome e numero in basso devono leggersi.</p>
      </div>
      {busy && <Spinner />}
      {error && <p class="error pad">{error}</p>}
      {result && (
        <div class="pad">
          {result.candidates.length > 0 ? (
            <>
              <h2 class="section">Quale di queste?</h2>
              <CardGrid cards={result.candidates} />
            </>
          ) : (
            <p class="muted">{result.message ?? "Non ho riconosciuto la carta."}
              {result.read?.name || result.read?.number ? ` Ho letto: ${[result.read.name, result.read.set_code, result.read.number].filter(Boolean).join(" ")}.` : ""}</p>
          )}
        </div>
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
