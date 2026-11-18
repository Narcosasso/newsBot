import type { ComponentChildren } from "preact";
import { useState } from "preact/hooks";
import { openCard } from "./nav";
import type { CardSummary } from "./api";

const PATHS: Record<string, ComponentChildren> = {
  search: (<><circle cx="11" cy="11" r="6.5" /><path d="M16 16l4.5 4.5" /></>),
  grid: (<><rect x="4" y="4" width="6.5" height="6.5" rx="1.5" /><rect x="13.5" y="4" width="6.5" height="6.5" rx="1.5" />
    <rect x="4" y="13.5" width="6.5" height="6.5" rx="1.5" /><rect x="13.5" y="13.5" width="6.5" height="6.5" rx="1.5" /></>),
  folder: (<path d="M3.5 7.5a2 2 0 0 1 2-2h4l2 2h7a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2h-13a2 2 0 0 1-2-2z" />),
  scan: (<><path d="M4 8V5.5A1.5 1.5 0 0 1 5.5 4H8M16 4h2.5A1.5 1.5 0 0 1 20 5.5V8M20 16v2.5a1.5 1.5 0 0 1-1.5 1.5H16M8 20H5.5A1.5 1.5 0 0 1 4 18.5V16" />
    <rect x="8.5" y="7.5" width="7" height="9" rx="1.2" /></>),
  dex: (<><rect x="5" y="3.5" width="11" height="15" rx="1.8" /><path d="M8.5 21h9.5a1.5 1.5 0 0 0 1.5-1.5V7" />
    <circle cx="10.5" cy="11" r="2.4" /></>),
  vault: (<><circle cx="12" cy="12" r="8.5" /><circle cx="12" cy="12" r="3.2" />
    <path d="M12 3.5v3M12 17.5v3M3.5 12h3M17.5 12h3M6 6l2.1 2.1M15.9 15.9L18 18M6 18l2.1-2.1M15.9 8.1L18 6" /></>),
  close: (<path d="M6 6l12 12M18 6L6 18" />),
  back: (<path d="M15 5l-7 7 7 7" />),
  share: (<><path d="M12 15V4M8 8l4-4 4 4" /><path d="M6 11v7.5A1.5 1.5 0 0 0 7.5 20h9a1.5 1.5 0 0 0 1.5-1.5V11" /></>),
  bell: (<><path d="M6 16.5V11a6 6 0 0 1 12 0v5.5l1.5 2h-15z" /><path d="M10 20.5a2 2 0 0 0 4 0" /></>),
  camera: (<><path d="M4 8.5A1.5 1.5 0 0 1 5.5 7h2.3l1.5-2h5.4l1.5 2h2.3A1.5 1.5 0 0 1 20 8.5v9a1.5 1.5 0 0 1-1.5 1.5h-13A1.5 1.5 0 0 1 4 17.5z" />
    <circle cx="12" cy="12.5" r="3.5" /></>),
  brush: (<path d="M14.5 4.5l5 5-7.5 7.5-5-5zM7 12l-2.5 2.5c-1 1-1 4.5-1 4.5s3.5 0 4.5-1L10.5 15.5" />),
  link: (<><path d="M10 14l7-7M12.5 7H17v4.5" /><path d="M17 14v3.5A1.5 1.5 0 0 1 15.5 19h-9A1.5 1.5 0 0 1 5 17.5v-9A1.5 1.5 0 0 1 6.5 7H10" /></>),
  check: (<path d="M5 12.5l4.5 4.5L19 7.5" />),
  logout: (<><path d="M14 5H6.5A1.5 1.5 0 0 0 5 6.5v11A1.5 1.5 0 0 0 6.5 19H14" /><path d="M11 12h9M17 9l3 3-3 3" /></>),
};

export function Icon({ name, size = 22 }: { name: string; size?: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8"
      stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
      {PATHS[name]}
    </svg>
  );
}

export function Spinner({ label }: { label?: string }) {
  return (
    <div class="spinner-wrap">
      <div class="spinner" />
      {label && <p class="muted">{label}</p>}
    </div>
  );
}

export function CardImage({ src, alt, class: cls = "" }: { src: string | null; alt: string; class?: string }) {
  const [broken, setBroken] = useState(false);
  return src && !broken ? (
    <img class={`card-img ${cls}`} src={src} alt={alt} loading="lazy" decoding="async" onError={() => setBroken(true)} />
  ) : (
    <div class={`card-img placeholder ${cls}`}><Icon name="dex" size={32} /><span>{alt}</span></div>
  );
}

export function CardTile({ card }: { card: CardSummary }) {
  return (
    <button class="tile" onClick={() => openCard(card.catalog_lang, card.id)}>
      <CardImage src={card.image} alt={card.name} />
      <span class="tile-name">{card.name}</span>
      <span class="tile-sub">
        {card.catalog_lang === "ja" && <span class="badge-jp">JP</span>}
        {card.number_label ?? card.number ?? ""}
      </span>
      <span class="tile-sub">{card.set_name}</span>
    </button>
  );
}

export function CardGrid({ cards }: { cards: CardSummary[] }) {
  return <div class="grid">{cards.map((c) => <CardTile key={`${c.catalog_lang}:${c.id}`} card={c} />)}</div>;
}

export function Header({ title, right }: { title: string; right?: ComponentChildren }) {
  return (
    <header class="screen-head">
      <h1>{title}</h1>
      {right && <div class="head-actions">{right}</div>}
    </header>
  );
}
