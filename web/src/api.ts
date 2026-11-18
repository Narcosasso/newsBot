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
};

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
  scan: (image: Blob) =>
    req<ScanResult>("/api/scan", { method: "POST", headers: { "Content-Type": image.type }, body: image }),
  tracking: () => req<{ trackings: TrackingInfo[] }>("/api/tracking"),
  track: (body: { card_id: string; catalog_lang: string; variant: string; langs: string[]; psa: boolean }) =>
    req<{ tracking: TrackingInfo }>("/api/tracking", { method: "PUT", ...json(body) }),
  untrack: (id: number) => req<{ ok: boolean }>(`/api/tracking/${id}`, { method: "DELETE" }),
};
