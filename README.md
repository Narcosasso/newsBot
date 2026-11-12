# Pokémon Card Price Bot (WhatsApp)

Bot WhatsApp personale: invii la foto di una carta Pokémon, il bot la riconosce (nome, set, numero, variante)
e risponde con i prezzi per le lingue che scegli (es. *ita, eng, jap*).

**Stato:** fase MVP (foto → riconoscimento → prezzi per lingua). Tracking e notifiche arrivano nella prossima fase.

## Cosa dicono davvero i prezzi

Il bot usa solo **fonti gratuite**: i prezzi Cardmarket e TCGplayer inclusi nel catalogo
[TCGdex](https://tcgdex.dev). Sono aggiornati una volta al giorno.

| Lingua | Cosa mostra | Specifico della lingua? |
|---|---|---|
| ITA, ENG, DEU, FRA, SPA, POR | Cardmarket: low, trend, media vendite, medie 7 e 30 giorni | **No**: Cardmarket vende queste lingue come un unico prodotto, quindi il prezzo è aggregato |
| ENG (in più) | TCGplayer: market e low in USD (mercato USA, quasi solo carte inglesi) | Sì, indicativamente |
| JAP | Cardmarket del prodotto giapponese | **Sì**: le carte giapponesi sono prodotti separati |
| KOR, CIN | Nessun prezzo: non esistono fonti gratuite | — |

Se fotografi una carta inglese e chiedi *jap* (o viceversa), il bot cerca la carta equivalente nell'altro
catalogo (stesso Pokémon, illustratore e PS) e la segnala come **equivalente stimato**.

L'API ufficiale di Cardmarket non accetta nuove registrazioni e le pagine del sito bloccano le richieste
automatiche: per questo il bot non legge le inserzioni per lingua.

## Come funziona

1. **Foto** → Claude vision legge nome, lingua, codice set, numero, regulation mark e indizi sulla variante.
2. **Match** sul catalogo TCGdex nella lingua della carta: prima set + numero, poi il nome come verifica.
   Le carte coreane si cercano nel catalogo giapponese (stessi set e numeri). Se il bot non è sicuro propone
   2-3 candidati con i bottoni; se la variante (normale / holo / reverse) non si capisce dalla foto, la chiede.
3. **Lingue**: le chiede (o le leggi dalla didascalia della foto) e ricorda le ultime usate.
4. **Prezzi** per lingua, con andamento (trend rispetto alle medie a 7 e 30 giorni), fonte e data di aggiornamento.

## Avvio in locale

Requisiti: Python 3.12+.

```bash
python -m venv .venv
```

```bash
source .venv/bin/activate
```

```bash
pip install -e ".[dev]"
```

```bash
cp .env.example .env
```

### Provare senza WhatsApp

Solo prezzi, senza nessuna chiave (id TCGdex della carta):

```bash
python -m cardbot.cli prices sv03.5-006 --variant holo --langs "ita, eng, jap"
```

Flusso completo da una foto (serve `ANTHROPIC_API_KEY` nel `.env`); se il bot ti fa domande rispondi nel terminale:

```bash
python -m cardbot.cli simulate foto_carta.jpg --langs "ita, jap"
```

### Test

```bash
pytest -q
```

### Server webhook

```bash
uvicorn cardbot.app:app --reload --port 8000
```

Per ricevere i messaggi da Meta in locale serve un URL HTTPS pubblico, per esempio con
[cloudflared](https://developers.cloudflare.com/cloudflare-one/connections/connect-networks/do-more-with-tunnels/trycloudflare/):

```bash
cloudflared tunnel --url http://localhost:8000
```

L'URL `https://…trycloudflare.com` stampato è quello da usare come *Callback URL* (con `/webhook` in fondo).

## Setup Meta / WhatsApp (Cloud API ufficiale)

1. **Account sviluppatore**: vai su [developers.facebook.com](https://developers.facebook.com), accedi con il tuo
   account Facebook e registrati come sviluppatore.
2. **Crea l'app**: *My Apps → Create app*. Scegli il caso d'uso WhatsApp (o tipo *Business*) e collega
   (o crea) un *Business portfolio*.
3. **Aggiungi WhatsApp** all'app. Nella pagina *WhatsApp → API Setup* Meta crea un **numero di test gratuito**:
   - copia il **Phone number ID** in `WHATSAPP_PHONE_NUMBER_ID`;
   - in *To* aggiungi il **tuo numero** come destinatario e confermalo con il codice ricevuto
     (il numero di test può scrivere solo a pochi destinatari verificati: per uso personale basta).
   - il *Temporary access token* dura 24 ore: va bene per una prima prova in `WHATSAPP_TOKEN`.
4. **App Secret**: *App settings → Basic → App secret* → `WHATSAPP_APP_SECRET`.
5. **Verify token**: inventa una stringa e mettila in `WHATSAPP_VERIFY_TOKEN`.
6. **Webhook**: avvia il server e il tunnel, poi in *WhatsApp → Configuration → Webhook*:
   - *Callback URL*: `https://<tuo-dominio>/webhook`
   - *Verify token*: lo stesso di `WHATSAPP_VERIFY_TOKEN` → *Verify and save*
   - in *Webhook fields* sottoscrivi **messages**.
7. **Token permanente** (al posto di quello da 24 ore): in [business.facebook.com](https://business.facebook.com)
   → *Settings → Users → System users* → aggiungi un system user (Admin) → *Assign assets*: l'app e il WhatsApp
   Business Account → *Generate token* con i permessi `whatsapp_business_messaging` e
   `whatsapp_business_management`, scadenza *Never*. Mettilo in `WHATSAPP_TOKEN`.
8. **Allowlist**: metti il tuo numero (prefisso senza `+`, es. `393331234567`) in `ALLOWED_WA_IDS`.
9. **Prova**: dal tuo WhatsApp scrivi *aiuto* al numero di test, poi manda la foto di una carta.

### Costi WhatsApp (verificati a novembre 2026, ricontrolla sulla
[pagina prezzi Meta](https://developers.facebook.com/documentation/business-messaging/whatsapp/pricing))

- Le risposte del bot entro 24 ore dal tuo ultimo messaggio sono *messaggi di servizio*: dal 1° ottobre 2026
  i primi 1.000 al mese per numero sono gratuiti. Per uso personale resti nella soglia.
- Le **notifiche** (prossima fase) partono quando non stai scrivendo al bot, quindi oltre la finestra di 24 ore:
  serve un **template "utility"** approvato da Meta (circa 0,03 $ a messaggio in Italia) e un metodo di pagamento
  in WhatsApp Manager. Il bot le raggrupperà in un solo messaggio per ciclo.

## Struttura

```
cardbot/
├── app.py                 # FastAPI: verifica webhook, firma, allowlist, dedup, elaborazione in background
├── bot/engine.py          # flusso della conversazione (indipendente dal trasporto)
├── bot/format.py          # testi in italiano
├── catalog/tcgdex.py      # client TCGdex con cache e limite di richieste
├── recognition/vision.py  # Claude vision con output JSON vincolato
├── recognition/matcher.py # match foto -> carta, punteggio e candidati
├── prices/                # quotazioni per lingua e scelta dei campi per variante
├── whatsapp/              # client Cloud API e parsing dei webhook
├── langs.py               # parsing "ita, eng, jap"
├── db.py                  # SQLAlchemy (SQLite in locale, Postgres in produzione)
└── cli.py                 # simulatore e lookup prezzi da terminale
```

## Prossime fasi

- **Tracking e notifiche**: "vuoi le notifiche?", job giornaliero sul price guide Cardmarket (un solo download
  al giorno, solo dopo che la fonte si è aggiornata), confronto con l'ultimo valore notificato, outbox
  idempotente, template utility.
- **Comandi**: lista, stop, modifica lingue, soglia (default ±10% e almeno 1 €).
- **Deploy**: Cloud Run (webhook) + Cloud Scheduler (job) + Neon (Postgres), segreti da Secret Manager.
