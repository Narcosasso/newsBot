"""Stima "tengo o vendo" di una carta: segnali di mercato -> probabilità che fra 30 giorni valga meno di oggi.

Non è una previsione affidabile: con le fonti gratuite abbiamo le medie Cardmarket dell'ultimo mese, il nostro
storico giornaliero (che cresce col tempo) e l'andamento del set. Il modello è volutamente semplice e trasparente:

1. ogni segnale dà un punteggio tra -1 (spinge al ribasso) e +1 (al rialzo), con un peso;
2. la media pesata, moltiplicata per MAX_MONTHLY_DRIFT, è la variazione attesa a 30 giorni (in log);
3. la volatilità stimata (dal nostro storico o dalla dispersione delle medie) dà l'incertezza;
4. P(ribasso) = Φ(-attesa / volatilità), avvicinata al 50% quando i dati sono pochi.
"""

from __future__ import annotations

import math
import statistics
from dataclasses import dataclass, field
from datetime import date

MAX_MONTHLY_DRIFT = 0.12   # con tutti i segnali al massimo: ±12% in un mese
CARDMARKET_FEE = 0.05      # commissione Cardmarket per i venditori privati (circa)
LOW_VALUE = 1.5            # sotto questa cifra vendere una carta singola non conviene

CHASE_RARITIES = ("special illustration", "illustration rare", "hyper", "secret", "ultra", "gold", "sir", "shiny")


@dataclass
class MarketInputs:
    price: float                     # prezzo di mercato attuale (trend)
    low: float | None = None
    avg1: float | None = None
    avg7: float | None = None
    avg30: float | None = None
    history: list[tuple[date, float]] = field(default_factory=list)   # nostro storico giornaliero (trend)
    set_change_7d: float | None = None    # mediana delle carte del set (frazione)
    set_change_30d: float | None = None
    set_share_up: float | None = None
    set_index: list[tuple[date, float]] = field(default_factory=list)  # somma dei prezzi del set nel tempo
    release_date: date | None = None
    rarity: str | None = None
    reprinted_recently: bool = False
    reprint_date: date | None = None
    other_prints: int = 0
    today: date | None = None


@dataclass
class Signal:
    key: str
    title: str
    detail: str
    score: float      # -1 … +1
    weight: float

    @property
    def direction(self) -> str:
        return "up" if self.score > 0.15 else "down" if self.score < -0.15 else "flat"


@dataclass
class Analysis:
    verdict: str            # hold | neutral | consider_selling | sell | low_value
    verdict_label: str
    summary: str
    p_down: float           # probabilità che fra 30 giorni valga meno di oggi
    expected_change: float  # variazione attesa a 30 giorni (frazione)
    range_low: float
    range_high: float
    confidence: str         # bassa | media | alta
    signals: list[Signal]
    net_if_sold: float
    notes: list[str]


def _pct(x: float) -> str:
    s = f"{abs(x) * 100:.1f}".replace(".", ",")
    return f"{'+' if x > 0 else '−' if x < 0 else ''}{s}%"


def _eur(x: float) -> str:
    return f"{x:,.2f} €".replace(",", "X").replace(".", ",").replace("X", ".")


def _slope_30d(points: list[tuple[date, float]]) -> float | None:
    """Pendenza (log) della regressione lineare, riportata a 30 giorni."""
    pts = [(d.toordinal(), math.log(v)) for d, v in points if v and v > 0]
    if len(pts) < 5:
        return None
    xs, ys = [p[0] for p in pts], [p[1] for p in pts]
    mx, my = statistics.fmean(xs), statistics.fmean(ys)
    den = sum((x - mx) ** 2 for x in xs)
    if den == 0:
        return None
    return sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / den * 30


def _phi(x: float) -> float:
    return 0.5 * (1 + math.erf(x / math.sqrt(2)))


def signals_for(m: MarketInputs) -> list[Signal]:
    out: list[Signal] = []
    p = m.price

    if m.avg30:
        x = math.log(p / m.avg30)
        out.append(Signal("trend30", "Ultimo mese",
                          f"Prezzo attuale {_pct(p / m.avg30 - 1)} rispetto alla media delle vendite degli ultimi "
                          f"30 giorni ({_eur(m.avg30)}).", math.tanh(x / 0.15), 0.25))
    if m.avg7:
        x = math.log(p / m.avg7)
        out.append(Signal("trend7", "Ultima settimana",
                          f"{_pct(p / m.avg7 - 1)} rispetto alla media dei 7 giorni ({_eur(m.avg7)}).",
                          math.tanh(x / 0.08), 0.15))
    if m.avg1 and m.avg7 and m.avg1 / m.avg7 > 1.3 and p >= 3:  # sotto i 3 € una sola vendita sposta la media
        out.append(Signal("spike", "Picco recente",
                          f"Le vendite di ieri ({_eur(m.avg1)}) sono molto sopra la media settimanale: dopo i picchi "
                          "il prezzo spesso torna indietro.", -0.6, 0.1))

    slope = _slope_30d(m.history[-60:])
    if slope is not None:
        out.append(Signal("history", f"Storico PokeVault ({len(m.history)} giorni)",
                          f"Tendenza dei prezzi registrati ogni notte: {_pct(math.exp(slope) - 1)} al mese.",
                          math.tanh(slope / 0.15), 0.2))

    if m.low and p:
        # Il "minimo" di Cardmarket include copie in qualsiasi condizione: di norma è circa 2/3 del prezzo di mercato.
        r = m.low / p
        score = max(-0.4, min(0.4, (r - 0.65) * 2))
        if r < 0.45:
            detail = (f"Ci sono copie in vendita a {_eur(m.low)}, molto sotto il prezzo di mercato (anche in "
                      "condizioni peggiori): offerta abbondante.")
        elif r > 0.85:
            detail = f"Le copie in vendita partono da {_eur(m.low)}, vicino al prezzo di mercato: offerta scarsa."
        else:
            detail = f"Copie in vendita da {_eur(m.low)} (anche in condizioni peggiori): offerta nella norma."
        out.append(Signal("supply", "Offerta", detail, score, 0.08))

    if m.set_change_30d is not None:
        card30 = (p / m.avg30 - 1) if m.avg30 else None
        set_part = math.tanh(m.set_change_30d / 0.1)
        rel = math.tanh((card30 - m.set_change_30d) / 0.15) if card30 is not None else 0.0
        share = f" ({round((m.set_share_up or 0) * 100)}% delle carte in salita)" if m.set_share_up is not None else ""
        extra = ""
        if card30 is not None:
            extra = (" La carta fa meglio del set." if card30 > m.set_change_30d + 0.03 else
                     " La carta fa peggio del set." if card30 < m.set_change_30d - 0.03 else
                     " La carta segue il set.")
        out.append(Signal("set", "Andamento del set",
                          f"Carta tipica del set {_pct(m.set_change_30d)} nell'ultimo mese{share}.{extra}",
                          0.6 * set_part + 0.4 * rel, 0.15))

    if m.release_date and m.today:
        age = (m.today - m.release_date).days
        if age < 0:
            score, detail = -0.6, "Set non ancora uscito ufficialmente: i prezzi delle prevendite sono instabili."
        elif age < 45:
            score, detail = -0.8, (f"Set uscito da {age} giorni: nei primi mesi i prezzi di solito scendono, perché "
                                   "si aprono tante buste.")
        elif age < 120:
            score, detail = -0.4, f"Set uscito da {age // 30} mesi: di solito la discesa post-uscita rallenta."
        elif age < 365:
            score, detail = 0.0, "Set in commercio da meno di un anno: prezzi di norma stabili."
        elif age < 730:
            score, detail = 0.2, "Set di oltre un anno fa: le buste iniziano a scarseggiare."
        else:
            score, detail = 0.35, ("Set di oltre due anni fa: di solito non si stampa più e le copie in circolazione "
                                   "diminuiscono.")
        chase = any(r in (m.rarity or "").lower() for r in CHASE_RARITIES)
        if chase and score < 0:
            score *= 0.7
            detail += " Le rarità più ricercate di solito reggono meglio."
        out.append(Signal("age", "Età del set", detail, score, 0.2))

    if m.reprinted_recently:
        when = f" il {m.reprint_date.strftime('%d/%m/%Y')}" if m.reprint_date else " di recente"
        out.append(Signal("reprint", "Ristampa",
                          f"La stessa carta (stesso testo) è uscita di nuovo in un altro prodotto{when}: più copie in "
                          "circolazione.", -0.5, 0.1))
    return out


def analyze(m: MarketInputs) -> Analysis:
    sigs = signals_for(m)
    total_w = sum(s.weight for s in sigs) or 1.0
    drift = MAX_MONTHLY_DRIFT * sum(s.score * s.weight for s in sigs) / total_w

    # Volatilità a 30 giorni: dal nostro storico se c'è, altrimenti dalla dispersione delle medie Cardmarket.
    sigma = None
    vals = [v for _, v in m.history[-60:] if v and v > 0]
    if len(vals) >= 8:
        rets = [math.log(b / a) for a, b in zip(vals, vals[1:])]
        sigma = statistics.pstdev(rets) * math.sqrt(30)
    if sigma is None:
        # Senza storico: volatilità di base delle carte singole (~10% al mese) più una parte della dispersione
        # delle medie (un calo deciso è soprattutto una direzione, già contata nei segnali, non solo rumore).
        disp = [abs(math.log(m.price / x)) for x in (m.avg7, m.avg30, m.avg1) if x]
        sigma = 0.10 + 0.4 * (max(disp) if disp else 0.15)
    if m.price < 2:
        sigma += 0.08
    sigma = min(0.4, max(0.06, sigma))

    p_down = _phi(-drift / sigma)
    points = (2 if m.avg30 else 0) + (1 if m.avg7 else 0) + (2 if len(m.history) >= 30 else 1 if len(m.history) >= 7
                                                               else 0) + (1 if m.set_change_30d is not None else 0)
    confidence = "alta" if points >= 5 else "media" if points >= 3 else "bassa"
    shrink = {"alta": 1.0, "media": 0.8, "bassa": 0.55}[confidence]
    p_down = round(min(0.9, max(0.1, 0.5 + (p_down - 0.5) * shrink)), 2)  # il verdetto usa la cifra mostrata

    net = max(0.0, m.price * (1 - CARDMARKET_FEE))
    notes = [f"Vendendola su Cardmarket incasseresti circa {_eur(net)} (commissione ~5%), spedizione esclusa."]
    if m.price < LOW_VALUE:
        verdict, label = "low_value", "Valore basso"
        summary = ("Vale poco: tra commissioni e spedizione vendere questa carta da sola non conviene. Tienila o "
                   "vendila in un lotto.")
    elif p_down >= 0.68:
        verdict, label = "sell", "Vendi"
        summary = "La maggior parte dei segnali indica un calo: se pensavi di venderla, questo è un buon momento."
    elif p_down >= 0.58:
        verdict, label = "consider_selling", "Valuta di vendere"
        summary = "I segnali pendono verso il ribasso, ma non in modo netto."
    elif p_down > 0.42:
        verdict, label = "neutral", "Neutrale"
        summary = "Segnali contrastanti: nessun motivo forte per vendere o per aspettare."
    else:
        verdict, label = "hold", "Tieni"
        summary = "I segnali indicano un prezzo stabile o in crescita: non c'è fretta di vendere."
    if confidence == "bassa":
        notes.append("Dati ancora scarsi: la stima diventa più affidabile man mano che PokeVault accumula lo storico.")
    if m.other_prints > 1:
        notes.append(f"Esistono {m.other_prints} stampe di questa carta su Cardmarket (set e versioni diverse).")

    return Analysis(
        verdict=verdict, verdict_label=label, summary=summary, p_down=round(p_down, 2),
        expected_change=round(math.exp(drift) - 1, 4),
        range_low=round(m.price * math.exp(drift - sigma), 2), range_high=round(m.price * math.exp(drift + sigma), 2),
        confidence=confidence, signals=sigs, net_if_sold=round(net, 2), notes=notes,
    )
