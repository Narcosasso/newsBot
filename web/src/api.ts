// Chiamate al server PokeVault (stessa origine: il cookie di sessione viaggia da solo).

export class AuthError extends Error {}

export type CardSummary = {
  id: string;
  catalog_lang: string;
  name: string;
  number?: string;
  number_label?: string;
  set_id?: string;
  set_name?: string;
  set_logo?: string | null;
  image: string | null;
  owned?: number;
};

export type SetBrief = { id: string; name: string; logo: string | null; symbol: string | null; total: number | null;
  official: number | null; owned: number };
export type SeriesGroup = { id: string; name: string; logo: string | null; release_date: string | null; sets: SetBrief[] };
export type SetDetail = {
  id: string; catalog_lang: string; name: string; logo: string | null; symbol: string | null; serie: string | null;
  code: string; release_date: string | null; total: number; official: number | null; owned_unique: number;
  owned_cards: number; owned_value: number; cards: CardSummary[];
};
export type Pokedex = { pokemon: [number, string, number, number][]; owned_species: number; total: number; pending: number };

export type Cardmarket = {
  currency: string;
  low: number | null;
  trend: number | null;
  avg: number | null;
  avg7: number | null;
  avg30: number | null;
  change_7d: number | null;
  change_30d: number | null;
  updated: string | null;
};

export type PriceGroup = {
  langs: string[];
  label: string;
  card_id: string | null;
  catalog_lang: string | null;
  card_label: string | null;
  aggregated: boolean;
  estimated: boolean;
  cardmarket: Cardmarket | null;
  tcgplayer: { currency: string; market: number | null; low: number | null } | null;
  notes: string[];
};

export type TrackingInfo = {
  id: number;
  card_id: string;
  catalog_lang: string;
  variant: string;
  label: string;
  langs: string[];
  psa: boolean;
  image?: string | null;
  targets: { source: string; langs: string[]; baseline: number | null; currency: string }[];
};

export type CardDetail = {
  id: string;
  catalog_lang: string;
  name: string;
  label: string;
  image: string | null;
  image_small: string | null;
  image_from_other_lang?: boolean;
  number: string;
  rarity: string | null;
  illustrator: string | null;
  dex_ids: number[];
  category: string | null;
  stats: {
    hp: number | null;
    types: string[];
    stage: string | null;
    evolve_from: string | null;
    weaknesses: { type: string; value?: string }[];
    resistances: { type: string; value?: string }[];
    retreat: number | null;
    regulation_mark: string | null;
  };
  set: {
    id: string;
    name: string;
    code: string;
    logo: string | null;
    serie: string | null;
    release_date: string | null;
    official: number | null;
    total: number | null;
  };
  variants: { variant: string; label: string; groups: PriceGroup[] }[];
  marketplaces: { name: string; url: string }[];
  tracking: TrackingInfo[];
  owned: OwnedItem[];
};

export type CollectionItem = {
  id: number;
  collection_id: number;
  card_id: string;
  catalog_lang: string;
  name: string;
  set_id: string | null;
  set_name: string | null;
  number_label: string | null;
  image: string | null;
  rarity: string | null;
  variant: string;
  variant_label: string | null;
  lang: string;
  quantity: number;
  unit_price: number | null;
  total: number | null;
  needs_review: boolean;
  added_at: string | null;
};

export type OwnedItem = CollectionItem & { collection_name: string };

export type CollectionTotals = { value: number; cards: number; unique: number; unpriced: number };
export type CollectionSummary = CollectionTotals & { id: number; name: string };
export type CollectionDetail = CollectionSummary & {
  history: { day: string; value: number; cards: number }[];
  items: CollectionItem[];
  pending_prices: number;
};

export type ImportReport = {
  collection_id: number;
  collection_name: string;
  imported: number;
  cards: number;
  review: { item_id: number; file: string; matched: string; card_id: string; catalog_lang: string }[];
  unmatched: { name: string; set: string; number: string; quantity: number; reason: string }[];
};

export type Graded = {
  available: boolean;
  reason?: string;
  source?: string;
  print?: string;
  tcgplayer_id?: string;
  usd_per_eur?: number | null;
  fx_date?: string | null;
  updated?: string | null;
  companies?: string[];
  grades?: {
    company: string;
    grade: string;
    price_usd: number | null;
    price_eur: number | null;
    median_usd: number | null;
    sales: number;
    trend: string | null;
  }[];
};

export type Analysis = {
  available: boolean;
  reason?: string;
  price: number;
  currency: string;
  updated: string | null;
  priced_card: string | null;
  priced_langs: string[];
  estimated_equivalent: boolean;
  verdict: "hold" | "neutral" | "consider_selling" | "sell" | "low_value";
  verdict_label: string;
  summary: string;
  p_down: number;
  p_up: number;
  expected_change: number;
  range_low: number;
  range_high: number;
  horizon_days: number;
  confidence: "bassa" | "media" | "alta";
  net_if_sold: number;
  notes: string[];
  signals: { key: string; title: string; detail: string; score: number; direction: "up" | "down" | "flat" }[];
  history: { day: string; price: number }[];
  averages: { label: string; value: number }[];
  set: null | { name: string; cards: number; change_7d: number | null; change_30d: number | null;
    share_up: number | null; index: { day: string; value: number }[] };
  release_date: string | null;
  disclaimer: string;
};

export type ScanResult = {
  found: boolean;
  confident?: boolean;
  message: string | null;
  candidates: CardSummary[];
  read?: { name: string | null; set_code: string | null; number: string | null };
};

async function req<T>(path: string, init: RequestInit = {}): Promise<T> {
  const resp = await fetch(path, { credentials: "same-origin", ...init });
  if (resp.status === 401) throw new AuthError("login");
  if (!resp.ok) {
    let message = `Errore ${resp.status}`;
    try {
      message = (await resp.json()).detail || message;
    } catch {
      /* risposta non JSON */
    }
    throw new Error(message);
  }
  return resp.json() as Promise<T>;
}

const json = (body: unknown): RequestInit => ({
  headers: { "Content-Type": "application/json" },
  body: JSON.stringify(body),
});

export const api = {
  me: () => req<{ app: string; photos: boolean; graded: boolean }>("/api/me"),
  login: (pin: string) => req<{ ok: boolean }>("/api/login", { method: "POST", ...json({ pin }) }),
  logout: () => req<{ ok: boolean }>("/api/logout", { method: "POST" }),
  search: (q: string, lang: string) =>
    req<{ cards: CardSummary[] }>(`/api/search?q=${encodeURIComponent(q)}&lang=${lang}`),
  recent: () => req<{ cards: CardSummary[] }>("/api/recent"),
  card: (lang: string, id: string) =>
    req<CardDetail>(`/api/cards/${encodeURIComponent(lang)}/${encodeURIComponent(id)}`),
  graded: (lang: string, id: string, variant: string) =>
    req<Graded>(`/api/cards/${encodeURIComponent(lang)}/${encodeURIComponent(id)}/graded?variant=${variant}`),
  sets: (lang: string) => req<{ series: SeriesGroup[]; owned_sets: number }>(`/api/sets?lang=${lang}`),
  set: (lang: string, id: string) =>
    req<SetDetail>(`/api/sets/${encodeURIComponent(lang)}/${encodeURIComponent(id)}`),
  pokedex: () => req<Pokedex>("/api/pokedex"),
  analysis: (lang: string, id: string, variant: string) =>
    req<Analysis>(`/api/cards/${encodeURIComponent(lang)}/${encodeURIComponent(id)}/analysis?variant=${variant}`),
  scan: (image: Blob) =>
    req<ScanResult>("/api/scan", { method: "POST", headers: { "Content-Type": image.type }, body: image }),
  tracking: () => req<{ trackings: TrackingInfo[] }>("/api/tracking"),
  track: (body: { card_id: string; catalog_lang: string; variant: string; langs: string[]; psa: boolean }) =>
    req<{ tracking: TrackingInfo }>("/api/tracking", { method: "PUT", ...json(body) }),
  untrack: (id: number) => req<{ ok: boolean }>(`/api/tracking/${id}`, { method: "DELETE" }),
  collections: () => req<{ collections: CollectionSummary[] }>("/api/collections"),
  collection: (id: number) => req<CollectionDetail>(`/api/collections/${id}`),
  createCollection: (name: string) =>
    req<{ id: number; name: string }>("/api/collections", { method: "POST", ...json({ name }) }),
  renameCollection: (id: number, name: string) =>
    req<{ id: number; name: string }>(`/api/collections/${id}`, { method: "PATCH", ...json({ name }) }),
  deleteCollection: (id: number) => req<{ ok: boolean }>(`/api/collections/${id}`, { method: "DELETE" }),
  refreshCollection: (id: number) => req<{ ok: boolean }>(`/api/collections/${id}/refresh`, { method: "POST" }),
  importCollection: (fileText: string) =>
    req<ImportReport>("/api/collections/import", {
      method: "POST", headers: { "Content-Type": "application/json" }, body: fileText,
    }),
  setItem: (body: { collection_id?: number; card_id: string; catalog_lang: string; variant: string; lang: string;
    quantity: number }) =>
    req<{ item: CollectionItem | null; owned: OwnedItem[] }>("/api/collection-items", { method: "PUT", ...json(body) }),
  confirmItem: (id: number) => req<{ ok: boolean }>(`/api/collection-items/${id}/confirm`, { method: "POST" }),
  deleteItem: (id: number) => req<{ ok: boolean }>(`/api/collection-items/${id}`, { method: "DELETE" }),
};
