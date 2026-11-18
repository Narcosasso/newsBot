import { useEffect, useState } from "preact/hooks";
import { api } from "../api";
import { Icon } from "../ui";

const isStandalone = () =>
  window.matchMedia("(display-mode: standalone)").matches || (navigator as unknown as { standalone?: boolean }).standalone === true;
const isIOS = () => /iPhone|iPad|iPod/.test(navigator.userAgent);
const pushSupported = () => "serviceWorker" in navigator && "PushManager" in window && "Notification" in window;

function keyBytes(base64url: string): Uint8Array<ArrayBuffer> {
  const pad = "=".repeat((4 - (base64url.length % 4)) % 4);
  const raw = atob((base64url + pad).replace(/-/g, "+").replace(/_/g, "/"));
  const out = new Uint8Array(new ArrayBuffer(raw.length));
  for (let i = 0; i < raw.length; i++) out[i] = raw.charCodeAt(i);
  return out;
}

/** Impostazioni: notifiche push dell'app e uscita. */
export function SettingsSheet({ onClose }: { onClose: () => void }) {
  const [state, setState] = useState<"checking" | "off" | "on" | "unsupported" | "needs-home" | "denied">("checking");
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState<string | null>(null);

  const check = async () => {
    if (isIOS() && !isStandalone()) return setState("needs-home");
    if (!pushSupported()) return setState("unsupported");
    if (Notification.permission === "denied") return setState("denied");
    const reg = await navigator.serviceWorker.ready;
    const sub = await reg.pushManager.getSubscription();
    if (!sub) return setState("off");
    const s = await api.pushStatus(sub.endpoint).catch(() => null);
    setState(s?.this_device ? "on" : "off");
  };
  useEffect(() => { check(); }, []);

  const enable = async () => {
    setBusy(true);
    setMsg(null);
    try {
      const perm = await Notification.requestPermission();  // deve partire dal tocco dell'utente
      if (perm !== "granted") {
        setState(perm === "denied" ? "denied" : "off");
        return;
      }
      const reg = await navigator.serviceWorker.ready;
      const { public_key } = await api.pushKey();
      const sub = (await reg.pushManager.getSubscription())
        ?? await reg.pushManager.subscribe({ userVisibleOnly: true, applicationServerKey: keyBytes(public_key) });
      await api.pushSubscribe(sub.toJSON());
      setState("on");
      setMsg("Notifiche attive su questo telefono.");
    } catch (e) {
      setMsg(`Non sono riuscito ad attivarle: ${(e as Error).message}`);
    } finally {
      setBusy(false);
    }
  };

  const disable = async () => {
    setBusy(true);
    try {
      const reg = await navigator.serviceWorker.ready;
      const sub = await reg.pushManager.getSubscription();
      if (sub) {
        await api.pushUnsubscribe(sub.endpoint);
        await sub.unsubscribe();
      }
      setState("off");
      setMsg("Notifiche disattivate su questo telefono.");
    } finally {
      setBusy(false);
    }
  };

  const test = async () => {
    setBusy(true);
    setMsg(null);
    try {
      await api.pushTest();
      setMsg("Inviata: dovrebbe arrivare tra qualche secondo.");
    } catch (e) {
      setMsg((e as Error).message);
    } finally {
      setBusy(false);
    }
  };

  const logout = async () => {
    await api.logout().catch(() => {});
    location.reload();
  };

  return (
    <div class="modal" onClick={onClose}>
      <div class="modal-card" onClick={(e) => e.stopPropagation()}>
        <h2>Impostazioni</h2>

        <h3><Icon name="bell" size={18} /> Notifiche</h3>
        <p class="muted small">Gli avvisi sui prezzi delle carte che segui arrivano qui come notifica, oltre che su WhatsApp.</p>
        {state === "checking" && <p class="muted">Controllo…</p>}
        {state === "needs-home" && (
          <p class="info-box"><Icon name="info" size={18} /><span>Su iPhone le notifiche funzionano solo dall'app sulla
            schermata Home: in Safari tocca <b>Condividi → Aggiungi alla schermata Home</b>, apri PokeVault dall'icona e torna qui.</span></p>
        )}
        {state === "unsupported" && <p class="muted">Questo browser non supporta le notifiche push.</p>}
        {state === "denied" && (
          <p class="info-box"><Icon name="info" size={18} /><span>Le notifiche sono bloccate: riattivale da
            <b> Impostazioni → Notifiche → PokeVault</b> sull'iPhone, poi torna qui.</span></p>
        )}
        {state === "off" && <button class="btn primary" onClick={enable} disabled={busy}>Attiva notifiche</button>}
        {state === "on" && (
          <div class="row gap">
            <span class="pill gold">✓ Attive su questo telefono</span>
            <button class="mini" onClick={test} disabled={busy}>Invia una prova</button>
            <button class="mini danger" onClick={disable} disabled={busy}>Disattiva</button>
          </div>
        )}
        {msg && <p class="small">{msg}</p>}

        <h3>Account</h3>
        <button class="btn ghost" onClick={logout}><Icon name="logout" size={18} /> Esci da PokeVault</button>
        <button class="btn primary" onClick={onClose}>Chiudi</button>
      </div>
    </div>
  );
}
