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
  value = Math.round(value * 10) / 10; // niente "−0,0%"
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

// Rarità come le chiama TCGdex (in inglese) -> nomi italiani usati sulle carte e da Cardmarket Italia.
const RARITY_IT: Record<string, string> = {
  "common": "Comune", "uncommon": "Non comune", "rare": "Rara", "rare holo": "Rara holo",
  "holo rare": "Rara holo", "double rare": "Doppia rara", "ultra rare": "Ultra rara",
  "illustration rare": "Rara illustrazione", "special illustration rare": "Rara illustrazione speciale",
  "hyper rare": "Iper rara", "mega hyper rare": "Mega iper rara", "secret rare": "Rara segreta",
  "shiny rare": "Rara cromatica", "shiny ultra rare": "Ultra rara cromatica", "ace spec rare": "Rara ASSO TATTICO",
  "radiant rare": "Rara lucente", "rare holo v": "Rara holo V", "holo rare v": "Rara holo V",
  "rare holo vmax": "Rara holo VMAX", "holo rare vmax": "Rara holo VMAX", "rare holo vstar": "Rara holo V ASTRO",
  "holo rare vstar": "Rara holo V ASTRO", "full art trainer": "Allenatore full art", "promo": "Promo",
  "rare prime": "Rara PRIME", "legend": "LEGGENDA", "none": "",
};

export function rarity(value: string | null | undefined): string {
  if (!value) return "";
  return RARITY_IT[value.trim().toLowerCase()] ?? value.charAt(0).toUpperCase() + value.slice(1);
}

/** Bandiera del catalogo della carta: le internazionali non hanno badge. */
export const CATALOG_BADGE: Record<string, string> = { ja: "JP", "zh-tw": "CN" };
