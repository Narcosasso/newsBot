# NewsBot

Bot Telegram che invia le notizie del giorno ogni mattina alle **08:00**, **10:30** e **20:30** (ora italiana) con:

1. Notizie dal Mondo
2. AI & Tecnologia
3. Serie A

Fonte: [The Guardian API](https://open-platform.theguardian.com/)

---

## Setup

### 1. Fork / push su GitHub

Carica questa cartella su un repository GitHub pubblico o privato.

### 2. Aggiungi i GitHub Secrets

Vai su **Settings → Secrets and variables → Actions → New repository secret** e crea:

| Nome | Valore |
|------|--------|
| `TELEGRAM_TOKEN` | Il token del tuo bot Telegram |
| `TELEGRAM_CHAT_ID` | Il tuo chat ID Telegram |
| `GUARDIAN_API_KEY` | La tua API key di The Guardian |

### 3. Abilita GitHub Actions

Vai su **Actions** nel repository e abilita i workflow se richiesto.

### 4. Test manuale

Dalla tab **Actions → News Bot → Run workflow**, spunta "Skip time check" per inviare subito un messaggio di prova.

---

## Struttura

```
newsBot/
├── news_bot.py                  # Script principale
├── requirements.txt             # Dipendenze Python
└── .github/
    └── workflows/
        └── news_bot.yml         # Workflow GitHub Actions
```

## Note sul timezone

GitHub Actions usa UTC. Il workflow schedula le esecuzioni sia per CET (UTC+1) che per CEST (UTC+2). Lo script Python verifica l'orario italiano reale con una finestra di ±25 minuti per evitare invii doppi.
