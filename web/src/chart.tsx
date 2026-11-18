import { useRef, useState } from "preact/hooks";
import { date, price } from "./format";

/** Grafico dei prezzi nel tempo: area, minimo e massimo, date agli estremi; toccando mostra giorno e valore. */
export function PriceChart({ points, currency = "EUR", height = 120 }: {
  points: { day: string; value: number }[]; currency?: string; height?: number;
}) {
  const box = useRef<HTMLDivElement>(null);
  const [hover, setHover] = useState<number | null>(null);
  if (points.length < 2) return null;
  const w = 320, h = height, pad = 6;
  const vals = points.map((p) => p.value);
  const min = Math.min(...vals), max = Math.max(...vals);
  const span = max - min || max * 0.1 || 1;
  const x = (i: number) => (i / (points.length - 1)) * w;
  const y = (v: number) => pad + (1 - (v - min) / span) * (h - pad * 2);
  const line = points.map((p, i) => `${i ? "L" : "M"}${x(i).toFixed(1)},${y(p.value).toFixed(1)}`).join(" ");
  const up = vals[vals.length - 1] >= vals[0];
  const color = up ? "var(--up)" : "var(--down)";
  const sel = hover ?? points.length - 1;

  const onMove = (e: PointerEvent) => {
    const r = box.current!.getBoundingClientRect();
    const i = Math.round(((e.clientX - r.left) / r.width) * (points.length - 1));
    setHover(Math.max(0, Math.min(points.length - 1, i)));
  };

  return (
    <div class="pchart" ref={box} onPointerMove={onMove} onPointerDown={onMove} onPointerLeave={() => setHover(null)}>
      <div class="pchart-head">
        <b>{price(points[sel].value, currency)}</b>
        <span class="muted">{date(points[sel].day)}</span>
      </div>
      <svg viewBox={`0 0 ${w} ${h}`} preserveAspectRatio="none" style={{ height: `${h}px` }} aria-hidden="true">
        <defs>
          <linearGradient id="pfill" x1="0" x2="0" y1="0" y2="1">
            <stop offset="0" stop-color={up ? "#3ddc84" : "#ff5f6d"} stop-opacity="0.28" />
            <stop offset="1" stop-color={up ? "#3ddc84" : "#ff5f6d"} stop-opacity="0" />
          </linearGradient>
        </defs>
        <path d={`${line} L${w},${h} L0,${h} Z`} fill="url(#pfill)" />
        <path d={line} fill="none" stroke={color} stroke-width="2.5" stroke-linejoin="round" vector-effect="non-scaling-stroke" />
        <line x1={x(sel)} x2={x(sel)} y1="0" y2={h} stroke="rgba(255,255,255,0.18)" vector-effect="non-scaling-stroke" />
      </svg>
      <div class="pchart-axis">
        <span>{date(points[0].day)}</span>
        <span>min {price(min, currency)} · max {price(max, currency)}</span>
        <span>{date(points[points.length - 1].day)}</span>
      </div>
    </div>
  );
}
