"""Flusso della conversazione: foto o testo -> carta (conferma carta/variante) -> lingue -> prezzi -> avvisi."""

from __future__ import annotations

import logging
from dataclasses import asdict, dataclass
from typing import Protocol

from sqlalchemy.orm import Session, sessionmaker

from cardbot.alerts.news import build_news
from cardbot.alerts.rules import Threshold, effective_threshold
from cardbot.alerts.tracking import CARDMARKET, PSA10, graded_spec, graded_specs, target_specs, upsert_tracking
from cardbot.bot.commands import Command, parse_command
from cardbot.bot.format import format_quotes, format_tracking_list, graded_line, help_text, welcome_text
from cardbot.db import Tracking, get_or_create_user, load_state, save_state, utcnow
from cardbot.langs import LANGS, full_name, parse_langs
from cardbot.prices.service import PriceService
from cardbot.recognition.matcher import Candidate, CardMatcher, MatchResult
from cardbot.recognition.text_query import TextQuery, parse_query
from cardbot.recognition.vision import CardVision, VisionError
from cardbot.variants import LABELS_IT, choose_variant

log = logging.getLogger(__name__)

YES = {"notify:yes", "si", "sì", "si avvisami", "sì, avvisami", "sì avvisami", "ok", "yes"}
WITH_PSA = {"notify:psa", "sì + psa 10", "si + psa 10", "sì + psa", "si + psa", "anche psa", "psa"}
NO = {"notify:no", "no", "no grazie", "no, grazie"}
NUMBERS = ["1️⃣", "2️⃣", "3️⃣"]

PHOTO_TIPS = "📸 Riprova con la carta dritta, ben illuminata e senza riflessi, con nome e numero leggibili."
TEXT_TIP = ("⌨️ Oppure scrivimi codice e numero stampati in basso a sinistra sulla carta, "
            "es. *MEW 006* o *30C 154/128*.")
NO_CARDS = ("Non segui ancora nessuna carta 🙂\n"
            "Cercane una (es. *30C 154*) e rispondi *Sì* quando ti chiedo degli avvisi.")


@dataclass
class Incoming:
    wa_id: str
    kind: str  # "text" | "image" | "button"
    text: str | None = None
    button_id: str | None = None
    image: bytes | None = None
    media_type: str = "image/jpeg"


class Messenger(Protocol):
    async def send_text(self, to: str, text: str) -> None: ...

    async def send_buttons(self, to: str, body: str, buttons: list[tuple[str, str]]) -> None: ...


def _name_and_set(label: str) -> tuple[str, str]:
    """('Gengar ex', '30th Celebration 154/128') da 'Gengar ex · 30th Celebration 154/128'."""
    name, _, rest = label.partition(" · ")
    return name, rest


def _langs_text(codes: list[str]) -> str:
    return ", ".join(full_name(c) for c in codes)


class Engine:
    def __init__(self, session_factory: sessionmaker[Session], messenger: Messenger, vision: CardVision,
                 matcher: CardMatcher, prices: PriceService, timezone: str = "Europe/Rome") -> None:
        self._sessions = session_factory
        self._out = messenger
        self._vision = vision
        self._matcher = matcher
        self._prices = prices
        self._tz = timezone

    @property
    def _photos(self) -> bool:
        return getattr(self._vision, "enabled", True)

    def _threshold_text(self, user) -> str:
        return Threshold(pct=user.threshold_pct, eur=user.threshold_eur).describe()

    async def handle(self, msg: Incoming) -> None:
        with self._sessions() as session:
            user, created = get_or_create_user(session, msg.wa_id)
            user.last_inbound_at = utcnow()  # apre (o rinnova) la finestra di servizio di 24 ore
            state = load_state(session, user)
            try:
                if created:
                    await self._out.send_text(user.wa_id, welcome_text(self._photos, self._threshold_text(user),
                                                                       self._prices.graded_enabled))
                    command = parse_command(msg.text or "") if msg.kind == "text" else None
                    if command is not None and command.kind == "help":
                        session.commit()
                        return  # "ciao" / "comandi" al primo messaggio: il benvenuto basta
                await self._dispatch(session, user, state, msg)
            except Exception:
                log.exception("Errore gestendo il messaggio di %s", msg.wa_id)
                save_state(state, "idle")
                await self._out.send_text(msg.wa_id, "😵 Ops, qualcosa è andato storto. Riprova tra un attimo.")
            session.commit()

    # --- smistamento -------------------------------------------------------------------------------

    async def _dispatch(self, session, user, state, msg: Incoming) -> None:
        if msg.kind == "image" and msg.image:
            await self._on_image(user, state, msg)
            return
        reply = (msg.button_id or msg.text or "").strip()
        lowered = reply.lower()
        if lowered.lstrip("/") in {"annulla", "reset"}:
            save_state(state, "idle")
            await self._out.send_text(user.wa_id, "👌 Ok, ricominciamo da capo.\n"
                                                  "Scrivimi il codice di una carta, es. *30C 154*.")
            return
        command = parse_command(reply) if msg.kind == "text" else None
        if command is not None:
            if command.kind == "langs" and command.index is None and state.stage == "awaiting_langs":
                await self._on_langs_reply(user, state, " ".join(command.langs))  # "lingue ita, jap" come risposta
            else:
                await self._on_command(session, user, state, command)
            return
        query = parse_query(reply) if msg.kind == "text" else None
        if query and query.is_specific and state.stage != "idle" and not parse_langs(reply).ok:
            await self._on_text_query(user, state, query)  # nuova ricerca a conversazione in corso
            return
        if state.stage == "awaiting_candidate":
            await self._on_candidate_reply(user, state, lowered)
        elif state.stage == "awaiting_variant":
            await self._on_variant_reply(user, state, lowered)
        elif state.stage == "awaiting_langs":
            await self._on_langs_reply(user, state, reply)
        elif state.stage == "awaiting_notify" and lowered in YES | NO | WITH_PSA:
            await self._on_notify_reply(session, user, state, lowered)
        elif query:
            await self._on_text_query(user, state, query)
        else:
            await self._out.send_text(user.wa_id, "🤔 Non ho capito.\nScrivimi codice e numero di una carta "
                                                  "(es. *30C 154*) oppure *comandi* per vedere cosa so fare.")

    # --- ricerca -----------------------------------------------------------------------------------

    async def _on_image(self, user, state, msg: Incoming) -> None:
        await self._out.send_text(user.wa_id, "🔍 Un attimo, guardo la foto…")
        try:
            vision = await self._vision.read_card(msg.image, msg.media_type)
        except VisionError as exc:
            await self._out.send_text(user.wa_id, f"⚠️ {exc}.")
            return
        if not vision.is_pokemon_card:
            await self._out.send_text(user.wa_id, f"🤔 Non mi sembra una carta Pokémon.\n{PHOTO_TIPS}")
            return

        result = await self._matcher.match(vision)
        if not result.candidates:
            read = " ".join(x for x in (vision.name, vision.set_code, vision.number) if x)
            seen = f"Ho letto «{read}», ma non" if read else "Non"
            await self._out.send_text(user.wa_id, f"😕 {seen} trovo la carta.\n{PHOTO_TIPS}\n{TEXT_TIP}")
            return
        caption = parse_langs(msg.text) if msg.text else None
        await self._present_match(user, state, result, hint=vision.variant_hint,
                                  langs=caption.langs if caption and caption.ok else None)

    async def _on_text_query(self, user, state, query: TextQuery) -> None:
        result = await self._matcher.match_text(query)
        if not result.candidates:
            await self._out.send_text(user.wa_id, "😕 Non trovo questa carta.\nControlla codice e numero in "
                                                  "basso a sinistra sulla carta, es. *MEW 006* o *30C 154/128*.")
            return
        await self._present_match(user, state, result, hint=query.variant or "unknown", langs=query.langs or None)

    async def _present_match(self, user, state, result: MatchResult, hint: str, langs: list[str] | None) -> None:
        payload = {
            "candidates": [asdict(c) for c in result.candidates],
            "hint": hint,  # variante letta dalla foto o scritta nel testo; usata se la carta la prevede
            "warnings": result.warnings,
            "langs": langs,
        }
        if result.confident:
            payload["selected"] = payload["candidates"][0]
            await self._after_card(user, state, payload)
            return

        save_state(state, "awaiting_candidate", payload)
        lines = ["🤔 Ho trovato più carte simili. Qual è la tua?", ""]
        for i, c in enumerate(result.candidates):
            name, rest = _name_and_set(c.short())
            lines.append(f"{NUMBERS[i]} *{name}* · {rest}")
        lines += ["", "Nessuna? Scrivimi codice e numero, es. *30C 154*."]
        buttons = [(f"cand:{i}", str(i + 1)) for i in range(len(result.candidates))]
        await self._out.send_buttons(user.wa_id, "\n".join(lines), buttons)

    async def _on_candidate_reply(self, user, state, reply: str) -> None:
        payload = dict(state.payload)
        cands = payload.get("candidates") or []
        idx = None
        if reply.startswith("cand:"):
            idx = int(reply.split(":", 1)[1])
        elif reply.isdigit():
            idx = int(reply) - 1
        if idx is None or not 0 <= idx < len(cands):
            await self._out.send_text(user.wa_id, f"Tocca un pulsante o scrivi un numero da 1 a {len(cands)} "
                                                  "(oppure *annulla*).")
            return
        payload["selected"] = cands[idx]
        await self._after_card(user, state, payload)

    # --- variante e lingue -------------------------------------------------------------------------

    async def _after_card(self, user, state, payload: dict) -> None:
        cand = Candidate(**payload["selected"])
        name, rest = _name_and_set(cand.short())
        variant = payload.get("variant") or choose_variant(cand.variants, payload.get("hint", "unknown"))
        if variant is None:
            save_state(state, "awaiting_variant", payload)
            buttons = [(f"var:{v}", LABELS_IT[v]) for v in cand.variants[:3]]
            await self._out.send_buttons(user.wa_id, f"🃏 *{name}*\n{rest}\n\nQuale versione hai?", buttons)
            return
        payload["variant"] = variant
        langs = payload.get("langs")
        if langs:
            await self._send_prices(user, state, payload, langs)
            return
        save_state(state, "awaiting_langs", payload)
        body = (f"✅ Trovata!\n🃏 *{name}*\n{rest} · {LABELS_IT[variant]}\n\n"
                "Per quali lingue vuoi i prezzi?\nScrivi ad esempio *ita*, *ita eng* o *ita jap*.")
        if user.langs:
            last = ", ".join(LANGS[c][0].lower() for c in user.langs.split(","))
            body += f"\n\nOppure tocca il pulsante per usare quelle dell'ultima volta ({last})."
            await self._out.send_buttons(user.wa_id, body, [("langs:last", "Come l'ultima volta")])
        else:
            await self._out.send_text(user.wa_id, body)

    async def _on_variant_reply(self, user, state, reply: str) -> None:
        payload = dict(state.payload)
        cand = Candidate(**payload["selected"])
        mapping = {"normale": "normal", "normal": "normal", "holo": "holo", "reverse": "reverse",
                   "reverse holo": "reverse"}
        if reply.startswith("var:"):
            variant = reply.split(":", 1)[1]
        elif reply.isdigit() and 1 <= int(reply) <= len(cand.variants):
            variant = cand.variants[int(reply) - 1]  # stesso ordine dei bottoni
        else:
            variant = mapping.get(reply)
        if variant not in cand.variants:
            options = ", ".join(f"*{LABELS_IT[v].lower()}*" for v in cand.variants)
            await self._out.send_text(user.wa_id, f"Scegli una di queste versioni: {options}.")
            return
        payload["variant"] = variant
        await self._after_card(user, state, payload)

    async def _on_langs_reply(self, user, state, reply: str) -> None:
        payload = dict(state.payload)
        if reply == "langs:last" and user.langs:
            langs = user.langs.split(",")
        else:
            parsed = parse_langs(reply)
            if not parsed.ok:
                unknown = f"Non conosco «{', '.join(parsed.unknown)}». " if parsed.unknown else ""
                await self._out.send_text(user.wa_id, f"🤔 {unknown}Scrivi le lingue così: *ita*, *ita eng*, "
                                                      "*ita jap*…\n(ita, eng, jap, kor, deu, fra, spa, por, cin)")
                return
            langs = parsed.langs
        await self._send_prices(user, state, payload, langs)

    async def _send_prices(self, user, state, payload: dict, langs: list[str]) -> None:
        cand = Candidate(**payload["selected"])
        variant = payload["variant"]
        quotes = await self._prices.quotes(cand.card_id, cand.catalog_lang, variant, langs)
        text = format_quotes(cand.short(), variant, quotes, tz=self._tz, warnings=payload.get("warnings"))
        await self._out.send_text(user.wa_id, text)
        user.langs = ",".join(langs)
        specs = target_specs(quotes)
        gspecs = graded_specs(quotes)
        next_payload = {"selected": payload["selected"], "variant": variant, "langs": langs, "targets": specs,
                        "graded_targets": gspecs}
        if not specs and not gspecs:
            save_state(state, "idle", next_payload)
            return
        save_state(state, "awaiting_notify", next_payload)
        buttons = [("notify:yes", "Sì, avvisami")] if specs else []
        if gspecs:
            buttons.append(("notify:psa", "Sì + PSA 10" if specs else "Sì, PSA 10"))
        buttons.append(("notify:no", "No, grazie"))
        await self._out.send_buttons(user.wa_id, "🔔 Vuoi che ti avvisi quando il prezzo cambia?", buttons)

    async def _on_notify_reply(self, session, user, state, reply: str) -> None:
        payload = dict(state.payload)
        save_state(state, "idle", payload)
        if reply in NO:
            await self._out.send_text(user.wa_id, "👌 Va bene, niente avvisi per questa carta.")
            return
        cand = Candidate(**payload["selected"])
        name, _ = _name_and_set(cand.short())
        with_psa = reply in WITH_PSA
        specs = list(payload.get("targets") or [])
        manage = {CARDMARKET}
        if with_psa:
            specs += payload.get("graded_targets") or []
            manage.add(PSA10)
        result = upsert_tracking(session, user, card_id=cand.card_id, catalog_lang=cand.catalog_lang,
                                 variant=payload["variant"], label=cand.short(), langs=payload["langs"],
                                 specs=specs, manage=frozenset(manage))
        th = effective_threshold(user, result.tracking)
        where = f" in {_langs_text(result.tracked_langs)}" if result.tracked_langs else ""
        lines = [f"✅ {'Fatto!' if result.created else 'Aggiornato!'} Seguo *{name}* "
                 f"({LABELS_IT[payload['variant']]}){where}."]
        if with_psa and result.graded:
            lines.append("🏅 Seguo anche il prezzo *PSA 10* (vendite USA, in dollari).")
        lines += [
                 f"🔔 Ti scrivo quando il prezzo sale o scende di almeno {th.describe()}.",
                 "⏰ Controllo i prezzi ogni mattina."]
        if result.untracked_langs:
            lines.append(f"⚠️ {_langs_text(result.untracked_langs)}: nessun prezzo disponibile, non posso "
                         "seguirlo.")
        lines += ["", "Scrivi *lista* per le tue carte o *novità* per gli ultimi movimenti."]
        await self._out.send_text(user.wa_id, "\n".join(lines))

    # --- comandi di gestione -------------------------------------------------------------------------

    def _trackings(self, session, user) -> list[Tracking]:
        return (session.query(Tracking).filter_by(user_id=user.id, active=True).order_by(Tracking.id).all())

    async def _pick(self, session, user, index: int | None) -> Tracking | None:
        """La carta n della lista (se ne segui una sola il numero si può omettere)."""
        trackings = self._trackings(session, user)
        if not trackings:
            await self._out.send_text(user.wa_id, NO_CARDS)
            return None
        if index is None and len(trackings) == 1:
            return trackings[0]
        if index is None or not 1 <= index <= len(trackings):
            await self._out.send_text(user.wa_id, f"Quale carta? Scrivi un numero da 1 a {len(trackings)}.\n\n"
                                                  + format_tracking_list(trackings, user))
            return None
        return trackings[index - 1]

    async def _on_command(self, session, user, state, cmd: Command) -> None:
        if cmd.kind == "help":
            await self._out.send_text(user.wa_id, help_text(self._photos, self._threshold_text(user),
                                                            self._prices.graded_enabled))
        elif cmd.kind == "supported_langs":
            names = "\n".join(f"• {full_name(c)} · *{LANGS[c][0].lower()}*" for c in LANGS)
            await self._out.send_text(user.wa_id, f"🌍 *Lingue che conosco*\n{names}")
        elif cmd.kind == "error":
            await self._out.send_text(user.wa_id, cmd.error)
        elif cmd.kind == "list":
            trackings = self._trackings(session, user)
            await self._out.send_text(user.wa_id, format_tracking_list(trackings, user) if trackings else NO_CARDS)
        elif cmd.kind == "news":
            await self._out.send_text(user.wa_id, build_news(session, user, self._tz))
        elif cmd.kind == "psa":
            await self._cmd_psa(session, user, cmd)
        elif cmd.kind == "stop":
            await self._cmd_stop(session, user, cmd)
        elif cmd.kind == "langs":
            await self._cmd_langs(session, user, cmd)
        elif cmd.kind == "threshold_show":
            await self._out.send_text(user.wa_id, (
                f"🔔 *Soglia degli avvisi:* ±{self._threshold_text(user)}\n"
                "Devono valere entrambe, così le carte economiche non ti riempiono di messaggi.\n\n"
                "Per cambiarla:\n"
                "• *soglia 15%* · *soglia 2€* · *soglia 15% 2€*\n"
                "• *soglia 15% 0€* · conta solo la percentuale\n"
                "• *soglia 1 20%* · solo per la carta 1 della lista"))
        elif cmd.kind == "threshold":
            await self._cmd_threshold(session, user, cmd)

    async def _cmd_stop(self, session, user, cmd: Command) -> None:
        if cmd.all:
            trackings = self._trackings(session, user)
            for t in trackings:
                t.active = False
            text = (f"🔕 Fatto, non seguo più nessuna carta ({len(trackings)} rimosse)." if trackings
                    else "Non seguivi nessuna carta 🙂")
            await self._out.send_text(user.wa_id, text)
            return
        tracking = await self._pick(session, user, cmd.index)
        if tracking is None:
            return
        tracking.active = False
        session.flush()
        name, rest = _name_and_set(tracking.label)
        text = f"🔕 Non seguo più *{name}* ({rest} · {LABELS_IT.get(tracking.variant, tracking.variant)})."
        remaining = self._trackings(session, user)
        if remaining:
            text += "\n\n" + format_tracking_list(remaining, user)
        await self._out.send_text(user.wa_id, text)

    async def _cmd_langs(self, session, user, cmd: Command) -> None:
        tracking = await self._pick(session, user, cmd.index)
        if tracking is None:
            return
        quotes = await self._prices.quotes(tracking.card_id, tracking.catalog_lang, tracking.variant, cmd.langs)
        specs = target_specs(quotes)
        if not specs:
            await self._out.send_text(user.wa_id, "⚠️ Per queste lingue non ci sono prezzi da seguire: lascio "
                                                  "tutto com'era.")
            return
        result = upsert_tracking(session, user, card_id=tracking.card_id, catalog_lang=tracking.catalog_lang,
                                 variant=tracking.variant, label=tracking.label, langs=cmd.langs, specs=specs)
        name, _ = _name_and_set(tracking.label)
        text = f"✅ *{name}*: ora seguo {_langs_text(result.tracked_langs)}."
        if result.untracked_langs:
            text += f"\n⚠️ {_langs_text(result.untracked_langs)}: nessun prezzo disponibile, non posso seguirlo."
        await self._out.send_text(user.wa_id, text)

    async def _cmd_threshold(self, session, user, cmd: Command) -> None:
        if cmd.index is None:
            if cmd.set_pct:
                user.threshold_pct = cmd.pct
            if cmd.set_eur:
                user.threshold_eur = cmd.eur
            custom = sum(1 for t in self._trackings(session, user) if t.threshold_custom)
            note = ""
            if custom == 1:
                note = "\n_(1 carta ha una soglia sua e resta com'è)_"
            elif custom > 1:
                note = f"\n_({custom} carte hanno una soglia loro e restano come sono)_"
            await self._out.send_text(user.wa_id, f"✅ Fatto! Ora ti avviso quando il prezzo cambia di almeno "
                                                  f"*±{self._threshold_text(user)}*.{note}")
            return
        tracking = await self._pick(session, user, cmd.index)
        if tracking is None:
            return
        name, _ = _name_and_set(tracking.label)
        if cmd.reset:
            tracking.threshold_custom = False
            await self._out.send_text(user.wa_id, f"✅ *{name}* torna alla soglia generale "
                                                  f"(±{self._threshold_text(user)}).")
            return
        if not tracking.threshold_custom:  # parte dalla soglia generale e cambia solo ciò che hai indicato
            tracking.threshold_pct, tracking.threshold_eur = user.threshold_pct, user.threshold_eur
            tracking.threshold_custom = True
        if cmd.set_pct:
            tracking.threshold_pct = cmd.pct
        if cmd.set_eur:
            tracking.threshold_eur = cmd.eur
        th = Threshold(pct=tracking.threshold_pct, eur=tracking.threshold_eur)
        await self._out.send_text(user.wa_id, f"✅ Per *{name}* ti avviso quando il prezzo cambia di almeno "
                                              f"*±{th.describe()}*.")

    async def _cmd_psa(self, session, user, cmd: Command) -> None:
        if not self._prices.graded_enabled:
            await self._out.send_text(user.wa_id, "I prezzi PSA 10 non sono attivi: serve la chiave "
                                                  "POKEMONPRICETRACKER_API_KEY nella configurazione del bot.")
            return
        tracking = await self._pick(session, user, cmd.index)
        if tracking is None:
            return
        name, _ = _name_and_set(tracking.label)
        langs = tracking.langs.split(",")
        if cmd.reset:
            upsert_tracking(session, user, card_id=tracking.card_id, catalog_lang=tracking.catalog_lang,
                            variant=tracking.variant, label=tracking.label, langs=langs, specs=[],
                            manage=frozenset({PSA10}))
            await self._out.send_text(user.wa_id, f"🔕 Non seguo più il prezzo PSA 10 di *{name}*.")
            return
        g = await self._prices.graded_quote(tracking.card_id, tracking.catalog_lang, tracking.variant)
        if g is None:
            await self._out.send_text(user.wa_id, f"😕 Non trovo prezzi PSA 10 per *{name}*.")
            return
        if not g.has_sales:
            await self._out.send_text(user.wa_id, f"😕 *{name}* non ha ancora vendite PSA 10: non c'è un prezzo "
                                                  "da seguire. Riprova più avanti.")
            return
        upsert_tracking(session, user, card_id=tracking.card_id, catalog_lang=tracking.catalog_lang,
                        variant=tracking.variant, label=tracking.label, langs=langs,
                        specs=[graded_spec(langs, tracking.card_id, tracking.catalog_lang, g)],
                        manage=frozenset({PSA10}))
        th = effective_threshold(user, tracking)
        await self._out.send_text(user.wa_id, f"✅ Seguo anche il prezzo PSA 10 di *{name}*.\n{graded_line(g)}\n"
                                              f"🔔 Ti scrivo quando cambia di almeno "
                                              f"{th.describe().replace('€', '$')}.")
