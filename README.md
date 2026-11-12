# Pokémon Card Price Bot (WhatsApp)

Bot WhatsApp personale: invii la foto di una carta Pokémon, il bot la riconosce (nome, set, numero, variante)
e risponde con i prezzi per le lingue che scegli (es. *ita, eng, jap*).
In alternativa scrivi codice set e numero (es. *MEW 006*): gratis, senza foto.

**Stato:** riconoscimento, prezzi per lingua, tracking e notifiche. Prossimi: comandi di gestione e deploy.

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
   **Oppure testo** → scrivi quello che è stampato in basso sulla carta. Non usa Claude, quindi non costa nulla:

   | Scrivi | Trova |
   |---|---|
   | `MEW 006` o `mew 6` | Charizard ex, 151 (inglese/internazionale) |
   | `SV2a 006/165` | リザードンex, ポケモンカード151 (giapponese) |
   | `Charizard ex 006/165` | per nome e numero, senza codice set |
   | `MEW 001 reverse ita jap` | con variante e lingue già indicate |

   Solo il nome (`Charizard ex`) propone fino a 3 candidati.
2. **Match** sul catalogo TCGdex nella lingua della carta: prima set + numero, poi il nome come verifica.
   Le carte coreane si cercano nel catalogo giapponese (stessi set e numeri). Se il bot non è sicuro propone
   2-3 candidati con i bottoni; se la variante (normale / holo / reverse) non si capisce dalla foto, la chiede.
3. **Lingue**: le chiede (o le leggi dalla didascalia della foto) e ricorda le ultime usate.
4. **Prezzi** per lingua, con andamento (trend rispetto alle medie a 7 e 30 giorni), fonte e data di aggiornamento.
5. **Notifiche**: il bot chiede "Vuoi una notifica quando il prezzo cambia?". Se rispondi sì salva la carta,
   la variante e le lingue, con il prezzo appena mostrato come valore di riferimento.

## Notifiche

- **Cosa si sorveglia:** il *trend* Cardmarket di ogni gruppo di lingue (ITA/ENG/… insieme, JAP a parte).
  KOR e CIN non hanno prezzi, quindi non sono tracciabili.
- **Quando scatta:** se il trend cambia di almeno **10% e almeno 1 €** rispetto all'**ultimo valore notificato**.
  Vanno superate entrambe le soglie, così una carta da 0,50 € non avvisa per +0,10 €. Il confronto è con
  l'ultimo valore notificato e non con il giorno prima, così una salita lenta ma continua prima o poi avvisa.
- **Mai doppioni:** uno snapshot per versione del price guide, una notifica per (prezzo, snapshot) con vincolo
  UNIQUE, il riferimento si aggiorna nella stessa transazione. L'invio è "al massimo una volta": un invio
  interrotto a metà non viene ripetuto, mentre un errore esplicito di WhatsApp viene ritentato al giro dopo.
- **Un messaggio per giro:** tutte le variazioni di un utente arrivano insieme.
- **Oltre le 24 ore:** se non scrivi al bot da più di 24 ore, WhatsApp accetta solo un template approvato
  (vedi sotto). Entro le 24 ore il bot manda un messaggio normale e gratuito.

### Job giornaliero

```bash
python -m cardbot.jobs.poll --dry-run
```

```bash
python -m cardbot.jobs.poll
```

- Scarica il [price guide Cardmarket](https://downloads.s3.cardmarket.com/productCatalog/priceGuide/price_guide_6.json)
  (circa 15 MB, rigenerato verso le 02:50 ora italiana) **con richiesta condizionale**: se il file non è cambiato
  il server risponde 304 e non si scarica nulla. È una sola richiesta al giorno, qualunque sia il numero di carte
  tracciate.
- Se il file non è raggiungibile ripiega su TCGdex (una richiesta per carta, con limite al secondo).
- Va schedulato **una volta al giorno, verso le 04:00 ora italiana**. Lanciarlo più spesso non crea doppioni.
- `--dry-run` mostra cosa notificherebbe senza salvare né inviare; `--force` rielabora anche un file già visto.

### Template WhatsApp per le notifiche

In [WhatsApp Manager](https://business.facebook.com/wa/manage/message-templates/) → *Message templates* →
*Create template*:

- **Categoria:** Utility · **Nome:** `price_alert` · **Lingua:** Italiano (`it`)
- **Corpo:**
  `Ciao! {{1}} variazioni di prezzo sulle carte Pokémon che segui: {{2}}. Scrivi al bot per vedere i prezzi aggiornati.`
- **Esempi:** `{{1}}` = `1`, `{{2}}` = `Charizard ex · 151 006/165 (Holo) — ITA: 8,13 € → 9,50 € +16,9%`

L'approvazione di solito arriva in pochi minuti. Nome e lingua si configurano con `WHATSAPP_ALERT_TEMPLATE` e
`WHATSAPP_TEMPLATE_LANG`. Per inviare template serve un metodo di pagamento in WhatsApp Manager.

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

Ricerca testuale come in chat, senza nessuna chiave (se il bot ti fa domande rispondi nel terminale):

```bash
python -m cardbot.cli search "MEW 006 ita jap"
```

Flusso completo da una foto (serve `ANTHROPIC_API_KEY` nel `.env`):

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
├── recognition/matcher.py # match foto/testo -> carta, punteggio e candidati
├── recognition/text_query.py # parsing di "MEW 006 reverse ita jap"
├── prices/                # quotazioni per lingua e scelta dei campi per variante
├── alerts/rules.py        # soglie e confronto (logica pura)
├── alerts/tracking.py     # carte seguite e prezzi sorvegliati
├── alerts/outbox.py       # snapshot, notifiche idempotenti, invio a digest (testo o template)
├── alerts/sources.py      # price guide Cardmarket (ETag) e fallback TCGdex
├── jobs/poll.py           # job giornaliero
├── whatsapp/              # client Cloud API e parsing dei webhook
├── langs.py               # parsing "ita, eng, jap"
├── db.py                  # SQLAlchemy (SQLite in locale, Postgres in produzione)
└── cli.py                 # simulatore e lookup prezzi da terminale
```

## Prossime fasi

- **Comandi**: lista, stop, modifica lingue, soglia (default ±10% e almeno 1 €).
- **Deploy**: Cloud Run (webhook) + Cloud Scheduler (job) + Neon (Postgres), segreti da Secret Manager.
