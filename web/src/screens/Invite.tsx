import { useEffect, useState } from "preact/hooks";
import { api } from "../api";
import { go } from "../nav";

/** Invito: chi apre il link sceglie nome e PIN e ha subito il suo account (amico di chi l'ha invitato). */
export function InviteScreen({ code, onDone }: { code: string; onDone: () => void }) {
  const [inviter, setInviter] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [name, setName] = useState("");
  const [pin, setPin] = useState("");
  const [pin2, setPin2] = useState("");
  const [busy, setBusy] = useState(false);

  useEffect(() => { api.inviteInfo(code).then((r) => setInviter(r.inviter)).catch((e) => setError((e as Error).message)); }, [code]);

  const submit = async (e: Event) => {
    e.preventDefault();
    if (pin !== pin2) return setError("I due PIN non coincidono.");
    setBusy(true);
    setError(null);
    try {
      await api.acceptInvite(code, name.trim(), pin);
      go("collection");
      onDone();
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(false);
    }
  };

  return (
    <form class="login" onSubmit={submit}>
      <img class="login-logo" src="/icons/icon-192.png" alt="" width={104} height={104} />
      <h1>PokeVault</h1>
      {inviter
        ? <p class="muted"><b>{inviter}</b> ti ha invitato: scegli come ti chiami e un PIN di 6-12 cifre per entrare.</p>
        : !error && <p class="muted">Controllo l'invito…</p>}
      {inviter && (
        <>
          <input class="input wide" placeholder="Il tuo nome" value={name} maxLength={30}
            onInput={(e) => setName((e.target as HTMLInputElement).value)} autoFocus />
          <input class="pin" type="password" inputMode="numeric" placeholder="PIN" value={pin} maxLength={12}
            onInput={(e) => setPin((e.target as HTMLInputElement).value.replace(/\D/g, ""))} autoComplete="new-password" />
          <input class="pin" type="password" inputMode="numeric" placeholder="Ripeti il PIN" value={pin2} maxLength={12}
            onInput={(e) => setPin2((e.target as HTMLInputElement).value.replace(/\D/g, ""))} autoComplete="new-password" />
          <button class="btn primary" type="submit" disabled={busy || name.trim().length < 2 || pin.length < 6}>
            {busy ? "Creo l'account…" : "Entra in PokeVault"}
          </button>
          <p class="muted small">Poi in Safari: Condividi → Aggiungi alla schermata Home.</p>
        </>
      )}
      {error && <p class="error">{error}</p>}
    </form>
  );
}
