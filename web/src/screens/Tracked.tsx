import { useEffect, useState } from "preact/hooks";
import { api, type TrackingInfo } from "../api";
import { LANG_CHIPS, price } from "../format";
import { openCard } from "../nav";
import { Header, Icon, Spinner } from "../ui";

const flagOf = (code: string) => LANG_CHIPS.find((l) => l.code === code)?.flag ?? code.toUpperCase();

export function TrackedScreen() {
  const [rows, setRows] = useState<TrackingInfo[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api.tracking().then((r) => setRows(r.trackings)).catch((e) => setError((e as Error).message));
  }, []);

  const logout = async () => {
    await api.logout().catch(() => {});
    location.reload();
  };

  return (
    <>
      <Header title="Collezione" right={
        <button class="round" onClick={logout} aria-label="Esci"><Icon name="logout" /></button>} />
      <div class="banner">
        <b>Collezioni in arrivo.</b> Qui potrai aggiungere le carte che possiedi, con varianti, quantità e valore.
      </div>
      <h2 class="section">Carte che segui</h2>
      {error && <p class="error pad">{error}</p>}
      {!rows && !error && <Spinner />}
      {rows && rows.length === 0 && (
        <p class="muted pad">Non segui ancora nessuna carta: aprine una e tocca <b>Segui questa carta</b>.</p>
      )}
      <div class="list">
        {rows?.map((t) => {
          const [name, rest] = t.label.split(" · ");
          return (
            <button class="list-row" onClick={() => openCard(t.catalog_lang, t.card_id)}>
              <div>
                <div class="strong">{name}</div>
                <div class="muted">{rest}</div>
              </div>
              <div class="right">
                {t.targets.map((x) => (
                  <div class="small">
                    {x.source === "psa10" ? "🏅 PSA 10" : x.langs.map(flagOf).join("")} {price(x.baseline, x.currency)}
                  </div>
                ))}
              </div>
            </button>
          );
        })}
      </div>
    </>
  );
}
