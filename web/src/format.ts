// Formattazione all'italiana: "62,18 €", "+3,8%", "12 nov 2026".

const money = new Map<string, Intl.NumberFormat>();

export function price(value: number | null | undefined, currency = "EUR"): string {
  if (value === null || value === undefined) return "—";
  if (!money.has(currency)) {
    money.set(currency, new Intl.NumberFormat("it-IT", { style: "currency", currency, currencyDisplay: "narrowSymbol" }));
  }
  return money.get(currency)!.format(value);
}

export function pct(value: number | null | undefined): string {
  if (value === null || value === undefined) return "—";
  const sign = value > 0 ? "+" : value < 0 ? "−" : "";
  return `${sign}${Math.abs(value).toLocaleString("it-IT", { maximumFractionDigits: 1, minimumFractionDigits: 1 })}%`;
}

export function trendClass(value: number | null | undefined): string {
  if (value === null || value === undefined || Math.abs(value) < 0.5) return "flat";
  return value > 0 ? "up" : "down";
}

export function date(value: string | null | undefined, withTime = false): string {
  if (!value) return "—";
  const d = new Date(value);
  return d.toLocaleDateString("it-IT", {
    day: "numeric",
    month: "short",
    year: "numeric",
    ...(withTime ? { hour: "2-digit", minute: "2-digit" } : {}),
  });
}

export const LANG_CHIPS = [
  { code: "it", label: "ITA", flag: "🇮🇹" },
  { code: "en", label: "ENG", flag: "🇬🇧" },
  { code: "de", label: "DEU", flag: "🇩🇪" },
  { code: "fr", label: "FRA", flag: "🇫🇷" },
  { code: "es", label: "SPA", flag: "🇪🇸" },
  { code: "pt", label: "POR", flag: "🇵🇹" },
  { code: "ja", label: "JAP", flag: "🇯🇵" },
];

export const TYPE_IT: Record<string, string> = {
  Grass: "Erba", Fire: "Fuoco", Water: "Acqua", Lightning: "Lampo", Psychic: "Psico", Fighting: "Lotta",
  Darkness: "Oscurità", Metal: "Metallo", Fairy: "Folletto", Dragon: "Drago", Colorless: "Incolore",
};

export const STAGE_IT: Record<string, string> = { Basic: "Base", Stage1: "Fase 1", Stage2: "Fase 2", VMAX: "VMAX",
  VSTAR: "V ASTRO", BREAK: "TURBO", MEGA: "Mega", "V-UNION": "V-UNIONE", Restored: "Ripristinato" };

export const plural = (n: number, one: string, many: string) => `${n} ${n === 1 ? one : many}`;
