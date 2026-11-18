import { useState } from "preact/hooks";
import { api } from "../api";
import { Icon } from "../ui";

export function LoginScreen({ onDone }: { onDone: () => void }) {
  const [pin, setPin] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const submit = async (e: Event) => {
    e.preventDefault();
    if (!pin) return;
    setBusy(true);
    setError(null);
    try {
      await api.login(pin);
      onDone();
    } catch (err) {
      setError((err as Error).message);
      setPin("");
    } finally {
      setBusy(false);
    }
  };

  return (
    <form class="login" onSubmit={submit}>
      <div class="login-logo"><Icon name="vault" size={56} /></div>
      <h1>PokeVault</h1>
      <p class="muted">Inserisci il PIN per entrare. Su questo telefono te lo chiedo una volta sola.</p>
      <input class="pin" type="password" inputMode="numeric" autoComplete="current-password" placeholder="PIN"
        value={pin} onInput={(e) => setPin((e.target as HTMLInputElement).value)} autoFocus />
      {error && <p class="error">{error}</p>}
      <button class="btn primary" type="submit" disabled={busy || !pin}>{busy ? "Controllo…" : "Entra"}</button>
    </form>
  );
}
