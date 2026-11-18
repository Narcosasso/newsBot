import { useEffect, useState } from "preact/hooks";
import { api, type TrackingInfo } from "../api";
import { LANG_CHIPS, price } from "../format";
import { openCard } from "../nav";
import { CardImage, Icon, Spinner } from "../ui";

const flagOf = (code: string) => LANG_CHIPS.find((l) => l.code === code)?.flag ?? code.toUpperCase();

/** Carte seguite (avvisi di prezzo), condivise con il bot WhatsApp. */
export function TrackedList() {
  const [rows, setRows] = useState<TrackingInfo[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api.tracking().then((r) => setRows(r.trackings)).catch((e) => setError((e as Error).message));
  }, []);

  return (
    <>
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
              <CardImage src={t.image ?? null} alt={name} class="thumb" />
              <div class="list-main">
                <div class="strong">{name}</div>
                <div class="muted small">{rest}</div>
                <div class="target-list">
                  {t.targets.map((x) => (
                    <span class="target">
                      <span class="target-tag">{x.source === "psa10" ? "PSA 10" : x.langs.map(flagOf).join(" ")}</span>
                      {price(x.baseline, x.currency)}
                    </span>
                  ))}
                </div>
              </div>
              <Icon name="chevron" size={18} />
            </button>
          );
        })}
      </div>
    </>
  );
}
