# Pokémon Card Price Bot (WhatsApp)

Bot WhatsApp personale: invii la foto di una carta Pokémon, il bot la riconosce (nome, set, numero, variante)
e risponde con i prezzi per le lingue che scegli (es. *ita, eng, jap*).
In alternativa scrivi codice set e numero (es. *MEW 006*): gratis, senza foto.

**Stato:** completo: riconoscimento, prezzi per lingua, tracking, notifiche, comandi e deploy su Google Cloud.

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

## Comandi in chat

| Comando | Cosa fa |
|---|---|
| `lista` | carte seguite, numerate, con prezzo di riferimento e soglia |
| `novità` | come si sono mossi i prezzi delle carte seguite: dal giorno prima, in 7 giorni e dal tuo riferimento |
| `stop 2` · `stop tutte` | smetti di seguire la carta 2, oppure tutte |
| `lingue 2 ita, jap` | cambia le lingue della carta 2; con una sola carta il numero si può omettere |
| `soglia` | mostra la soglia generale |
| `soglia 15%` · `soglia 2€` · `soglia 15% 2€` | cambia la soglia generale; `0%` o `0€` disattiva quella condizione |
| `soglia 2 20%` · `soglia 2 predefinita` | soglia solo per la carta 2, oppure ritorno a quella generale |
| `comandi` (o `/comandi`, `aiuto`, `menu`) · `lingue` · `annulla` | guida · lingue supportate · ricomincia |

Al primo messaggio il bot si presenta e manda la lista dei comandi. Lo `/` iniziale è facoltativo per tutti i comandi. I comandi funzionano anche a metà di una ricerca. I numeri sono quelli di `lista`: dopo uno `stop` il bot
rimanda la lista aggiornata. Cambiare lingue mantiene il riferimento delle lingue già seguite; le nuove partono
dal prezzo attuale.

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
migrations/                # Alembic
deploy/gcp.sh              # deploy su Google Cloud
deploy/entrypoint.sh       # avvio container: migrazioni, poi webhook o job
Dockerfile
```

## Deploy (Google Cloud Run + Neon, uso personale ≈ 0 €)

Architettura:

| Pezzo | Servizio | Note |
|---|---|---|
| Webhook WhatsApp | **Cloud Run service** `cardbot` | URL HTTPS pubblico incluso, scala a zero, max 1 istanza |
| Controllo prezzi giornaliero | **Cloud Run job** `cardbot-poll` | stessa immagine, avviato da Cloud Scheduler alle 04:00 (Europe/Rome) |
| Database | **Neon** (Postgres gestito) | piano Free; lo schema lo crea Alembic a ogni avvio del container |
| Segreti | **Secret Manager** | token Meta, App Secret, verify token, chiave Anthropic, URL del database |

### Tutto dal telefono

Si può fare tutto dal browser del telefono, senza computer. Per i siti di Meta (developers.facebook.com,
business.facebook.com, WhatsApp Manager) attiva **"Sito desktop"** nel browser: alcune pagine su mobile rimandano
all'app o nascondono dei menu.

1. **Neon** (passo 1 qui sotto) e **Meta** (sezione "Setup Meta / WhatsApp", salta il tunnel locale): tutto da browser.
   Copia i valori in una nota mentre li ottieni.
2. **Google Cloud**: progetto, fatturazione e budget dalla [console](https://console.cloud.google.com) (passo 2,
   tranne l'installazione di gcloud, che non serve).
3. Apri **[Cloud Shell](https://shell.cloud.google.com)**: un terminale nel browser con `gcloud` e `git` già pronti
   e già collegato al tuo account. Scarica il progetto (se il repository è privato, GitHub chiede utente e un
   [token personale](https://github.com/settings/personal-access-tokens) con permesso di sola lettura al posto
   della password):

```bash
git clone -b claude/vibrant-thompson-q8qql6 https://github.com/Narcosasso/newsBot.git && cd newsBot
```

4. Crea il `.env` e incolla i valori (in nano: salva con *Ctrl+O*, Invio, esci con *Ctrl+X*; sulla tastiera di
   Cloud Shell da telefono c'è il tasto *Ctrl*):

```bash
cp .env.example .env && nano .env
```

5. Lancia il deploy con il tuo Project ID:

```bash
PROJECT_ID=cardbot-123456 ./deploy/gcp.sh all
```

6. Copia il **Callback URL** stampato alla fine e incollalo nel webhook su Meta (passo 4). Poi scrivi *aiuto* al bot.

Il `.env` resta nella cartella personale di Cloud Shell, protetta dal tuo account Google. Se preferisci, cancellalo
dopo il deploy: i segreti sono già in Secret Manager.

**Puoi partire anche senza la chiave Anthropic**: lascia vuoto `ANTHROPIC_API_KEY` e il bot funziona con la
ricerca testuale (*MEW 006*), gratis. A una foto risponde spiegando di scrivere codice set e numero. Per attivare
le foto più avanti, aggiungi la chiave al `.env` e rilancia `./deploy/gcp.sh secrets` e poi `./deploy/gcp.sh deploy`.

### 1. Database su Neon

1. Crea un account su [neon.com](https://neon.com) (piano Free, senza carta).
2. *New project*: regione **AWS Europe (Frankfurt)**, Postgres 16 o successivo.
3. *Connect* → copia la connection string (va bene quella *pooled*), es.
   `postgresql://utente:password@ep-xxx-pooler.eu-central-1.aws.neon.tech/neondb?sslmode=require`
4. Mettila in `DATABASE_URL` nel tuo `.env` (il bot aggiunge da solo il driver `psycopg`).

### 2. Progetto Google Cloud

1. Crea un account su [console.cloud.google.com](https://console.cloud.google.com) e un **progetto** (annota il
   *Project ID*, es. `cardbot-123456`).
2. *Billing*: collega un account di fatturazione. Serve una carta anche se resti nelle quote gratuite.
3. **Avviso di budget** (consigliato): *Billing → Budgets & alerts → Create budget*, importo **1 €**, avvisi al
   50/90/100%. Ti scrive un'email se qualcosa inizia a costare.
4. Installa la [gcloud CLI](https://cloud.google.com/sdk/docs/install) e accedi:

```bash
gcloud auth login
```

### 3. Deploy

Compila il `.env` completo (Meta, Anthropic, Neon, `ALLOWED_WA_IDS`), poi dalla cartella del progetto:

```bash
PROJECT_ID=cardbot-123456 ./deploy/gcp.sh all
```

Lo script, rilanciabile:

- `setup` abilita le API (Cloud Run, Scheduler, Secret Manager, Artifact Registry, Cloud Build) e crea due
  service account con i soli permessi necessari;
- `secrets` copia in Secret Manager i 5 segreti dal `.env`, passandoli da stdin; crea una nuova versione solo
  se il valore è cambiato;
- `deploy` costruisce l'immagine con Cloud Build (`.env` escluso dal caricamento tramite `.gcloudignore`), pubblica
  il webhook e il job con la stessa immagine e tiene solo le ultime 2 immagini;
- `schedule` pianifica il job ogni giorno alle 04:00 ora italiana;
- alla fine stampa il **Callback URL**, es. `https://cardbot-xxxx.europe-west1.run.app/webhook`.

### 4. Collega Meta

In *WhatsApp → Configuration → Webhook* sostituisci il Callback URL (quello del tunnel locale) con l'URL stampato,
stesso verify token, *Verify and save*, campo **messages** sottoscritto. Poi scrivi *aiuto* al bot.

### Se il bot non risponde

Leggi i log del webhook:

```bash
gcloud run services logs read cardbot --region europe-west1 --limit 30
```

- **Nessun `POST /webhook`** quando gli scrivi: l'account WhatsApp non è iscritto alla tua app (succede col
  numero di prova). Iscrivila usando il token permanente del `.env`; `WABA_ID` è l'*ID dell'account di
  messaggistica* mostrato nella pagina di prova su Meta. Il primo comando legge il token, il secondo controlla
  le app iscritte, il terzo iscrive la tua.

```bash
TOKEN=$(grep '^WHATSAPP_TOKEN=' .env | cut -d= -f2-)
```

```bash
curl -s "https://graph.facebook.com/v25.0/WABA_ID/subscribed_apps" -H "Authorization: Bearer $TOKEN"; echo
```

```bash
curl -s -X POST "https://graph.facebook.com/v25.0/WABA_ID/subscribed_apps" -H "Authorization: Bearer $TOKEN"; echo
```

- **`POST /webhook` con 403**: `WHATSAPP_APP_SECRET` non corrisponde all'App secret dell'app.
- **`Messaggio ignorato: il mittente non è in ALLOWED_WA_IDS`**: correggi il numero (prefisso senza `+`).
- **`WhatsApp send error`**: il token permanente non ha i permessi o l'account WhatsApp non è assegnato
  all'utente di sistema.
- `/healthz` su Cloud Run dà un 404 di Google: è un percorso riservato. Usa `/health`.

### Operazioni utili

Eseguire subito il controllo prezzi:

```bash
gcloud run jobs execute cardbot-poll --region europe-west1 --wait
```

Log del webhook:

```bash
gcloud run services logs read cardbot --region europe-west1 --limit 50
```

Dopo una modifica al codice (le migrazioni del database partono da sole all'avvio):

```bash
PROJECT_ID=cardbot-123456 ./deploy/gcp.sh deploy
```

Dopo aver cambiato un segreto nel `.env`:

```bash
PROJECT_ID=cardbot-123456 ./deploy/gcp.sh secrets
```

```bash
PROJECT_ID=cardbot-123456 ./deploy/gcp.sh deploy
```

### Costi attesi (quote verificate a novembre 2026, ricontrolla le pagine ufficiali)

- **Cloud Run**: il webhook usa la CPU sempre allocata, perché la foto si elabora dopo aver già risposto a Meta.
  Quota gratuita mensile con questa modalità: 240.000 vCPU-secondi e 450.000 GiB-secondi
  ([prezzi](https://cloud.google.com/run/pricing)). Un'istanza resta accesa fino a circa 15 minuti dopo l'ultimo
  messaggio, quindi circa 900 vCPU-secondi per conversazione: circa 250 conversazioni al mese gratis. Il job usa
  circa un minuto al giorno.
- **Cloud Scheduler**: 3 job gratuiti per account di fatturazione (ne usiamo 1).
- **Secret Manager, Artifact Registry, Cloud Build**: nelle quote gratuite con questo uso.
- **Neon Free**: 1 GB e 100 ore di calcolo al mese per progetto; il database si sospende dopo 5 minuti di
  inattività (il primo messaggio dopo una pausa è più lento di uno o due secondi).
- Restano i costi d'uso già visti: Claude per le foto (circa 1-4 centesimi a foto) e i template WhatsApp oltre le
  24 ore (circa 0,03 $).

### Database e migrazioni

Lo schema è gestito da **Alembic** (`migrations/`). Il container esegue `alembic upgrade head` a ogni avvio; in
locale con SQLite le tabelle si creano da sole. Se cambi i modelli in `cardbot/db.py`:

```bash
alembic revision --autogenerate -m "descrizione"
```

Il test `tests/test_migrations.py` fallisce se migrazioni e modelli non coincidono.
