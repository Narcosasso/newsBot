import { useEffect, useMemo, useState } from "preact/hooks";
import { api, type Pokedex } from "../api";
import { Header, Icon, Spinner } from "../ui";
import { searchFor } from "./Search";

const GENS = ["Tutte", "I", "II", "III", "IV", "V", "VI", "VII", "VIII", "IX"];
const sprite = (n: number) => `https://raw.githubusercontent.com/PokeAPI/sprites/master/sprites/pokemon/${n}.png`;
let lastGen = 0;
let lastOnly = "all";

export function PokedexScreen() {
  const [data, setData] = useState<Pokedex | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [gen, setGen] = useState(lastGen);
  const [only, setOnly] = useState(lastOnly);
  const [q, setQ] = useState("");

  const load = () => api.pokedex().then(setData).catch((e) => setError((e as Error).message));
  useEffect(() => { load(); }, []);
  useEffect(() => {  // numeri Pokédex delle carte importate in completamento: ricarico tra poco
    if (!data?.pending) return;
    const t = setTimeout(load, 5000);
    return () => clearTimeout(t);
  }, [data]);
  useEffect(() => { lastGen = gen; lastOnly = only; }, [gen, only]);

  const list = useMemo(() => {
    const needle = q.trim().toLowerCase().replace(/^#0*/, "");
    return (data?.pokemon ?? []).filter(([n, name, g, owned]) => (!gen || g === gen)
      && (only === "all" || (only === "owned" ? owned > 0 : owned === 0))
      && (!needle || name.toLowerCase().includes(needle) || String(n) === needle));
  }, [data, gen, only, q]);

  return (
    <>
      <Header title="Pokédex" />
      {data && (
        <div class="dex-summary">
          <b>{data.owned_species}</b> Pokémon su {data.total} nella tua collezione
          <div class="progress"><div style={{ width: `${(data.owned_species / data.total) * 100}%` }} /></div>
          {data.pending > 0 && <p class="value-note"><span class="dot" /> Completo i dati di {data.pending} carte…</p>}
        </div>
      )}
      <div class="searchbar">
        <Icon name="search" size={20} />
        <input type="search" placeholder="Nome o numero" value={q} onInput={(e) => setQ((e.target as HTMLInputElement).value)} />
      </div>
      <div class="chips">
        {[["all", "Tutti"], ["owned", "Che ho"], ["missing", "Che mi mancano"]].map(([id, label]) => (
          <button class={`chip ${only === id ? "on" : ""}`} onClick={() => setOnly(id)}>{label}</button>
        ))}
      </div>
      <div class="chips">
        {GENS.map((g, i) => <button class={`chip ${gen === i ? "on" : ""}`} onClick={() => setGen(i)}>{i ? `Gen ${g}` : g}</button>)}
      </div>
      {error && <p class="error pad">{error}</p>}
      {!data && !error && <Spinner />}
      <div class="dex-grid">
        {list.map(([n, name, , owned]) => (
          <button class={`dex-cell ${owned ? "owned" : ""}`} onClick={() => searchFor(`#${n}`)}>
            <img src={sprite(n)} alt="" loading="lazy" width={72} height={72} />
            <span class="dex-num">#{String(n).padStart(4, "0")}</span>
            <span class="dex-name">{name}</span>
            {owned > 0 && <span class="dex-owned">{owned}</span>}
          </button>
        ))}
      </div>
    </>
  );
}
