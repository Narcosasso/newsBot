#!/usr/bin/env bash
# Deploy su Google Cloud: Cloud Run (webhook) + Cloud Run job (controllo prezzi) + Cloud Scheduler + Secret Manager.
#
#   PROJECT_ID=mio-progetto ./deploy/gcp.sh all        # tutto, nell'ordine
#   PROJECT_ID=mio-progetto ./deploy/gcp.sh setup      # API, service account e permessi
#   PROJECT_ID=mio-progetto ./deploy/gcp.sh secrets    # copia i segreti dal .env in Secret Manager
#   PROJECT_ID=mio-progetto ./deploy/gcp.sh deploy     # build dell'immagine, servizio e job
#   PROJECT_ID=mio-progetto ./deploy/gcp.sh schedule   # job ogni giorno alle 04:00 ora italiana
#   PROJECT_ID=mio-progetto ./deploy/gcp.sh url        # URL del webhook da inserire su Meta
#
# Ogni comando si può rilanciare: aggiorna ciò che esiste già.
set -euo pipefail

: "${PROJECT_ID:?Imposta PROJECT_ID, es. PROJECT_ID=cardbot-123456}"
REGION="${REGION:-europe-west1}"        # regione di livello 1 (quota gratuita piena)
SERVICE="${SERVICE:-cardbot}"
JOB="${JOB:-cardbot-poll}"
ENV_FILE="${ENV_FILE:-.env}"
SCHEDULE="${SCHEDULE:-0 4 * * *}"
TIME_ZONE="${TIME_ZONE:-Europe/Rome}"

RUNTIME_SA="cardbot-runtime@${PROJECT_ID}.iam.gserviceaccount.com"
SCHEDULER_SA="cardbot-scheduler@${PROJECT_ID}.iam.gserviceaccount.com"

SECRETS=(WHATSAPP_TOKEN WHATSAPP_APP_SECRET WHATSAPP_VERIFY_TOKEN DATABASE_URL
         ANTHROPIC_API_KEY POKEMONPRICETRACKER_API_KEY)
# Facoltativi: senza, il bot funziona lo stesso (foto con Google Vision, niente prezzi PSA 10).
OPTIONAL_SECRETS=" ANTHROPIC_API_KEY POKEMONPRICETRACKER_API_KEY "
PLAIN_VARS=(WHATSAPP_PHONE_NUMBER_ID WHATSAPP_API_VERSION ALLOWED_WA_IDS WHATSAPP_ALERT_TEMPLATE
            WHATSAPP_TEMPLATE_LANG PHOTO_READER VISION_MODEL VISION_EFFORT TIMEZONE TCGDEX_MAX_RPS)

gc() { gcloud --project "$PROJECT_ID" "$@"; }

# Valore di una variabile nel file .env (senza eseguirlo), togliendo eventuali virgolette.
env_value() {
  local line
  line="$(grep -E "^$1=" "$ENV_FILE" | tail -n 1 || true)"
  line="${line#*=}"
  line="${line%\"}"; line="${line#\"}"
  line="${line%\'}"; line="${line#\'}"
  printf '%s' "$line"
}

cmd_setup() {
  gc services enable run.googleapis.com cloudscheduler.googleapis.com secretmanager.googleapis.com \
    artifactregistry.googleapis.com cloudbuild.googleapis.com vision.googleapis.com
  for sa in cardbot-runtime cardbot-scheduler; do
    gc iam service-accounts describe "${sa}@${PROJECT_ID}.iam.gserviceaccount.com" >/dev/null 2>&1 \
      || gc iam service-accounts create "$sa" --display-name "$sa"
  done
  # Il servizio e il job leggono i segreti e usano le API del progetto (Cloud Vision per le foto).
  for role in roles/secretmanager.secretAccessor roles/serviceusage.serviceUsageConsumer; do
    gc projects add-iam-policy-binding "$PROJECT_ID" --member "serviceAccount:${RUNTIME_SA}" \
      --role "$role" --condition None >/dev/null
  done
  # Nei progetti nuovi l'account che esegue le build ("run deploy --source") non riceve più i permessi in
  # automatico: gli diamo il ruolo Cloud Run Builder e l'uso dei servizi del progetto.
  local number build_sa
  number="$(gc projects describe "$PROJECT_ID" --format 'value(projectNumber)')"
  build_sa="${number}-compute@developer.gserviceaccount.com"
  for role in roles/run.builder roles/serviceusage.serviceUsageConsumer; do
    gc projects add-iam-policy-binding "$PROJECT_ID" --member "serviceAccount:${build_sa}" \
      --role "$role" --condition None >/dev/null
  done
  echo "Setup completato (i permessi nuovi possono impiegare qualche minuto ad attivarsi)."
}

cmd_secrets() {
  [ -f "$ENV_FILE" ] || { echo "File $ENV_FILE non trovato" >&2; exit 1; }
  for name in "${SECRETS[@]}"; do
    value="$(env_value "$name")"
    if [ -z "$value" ]; then
      echo "ATTENZIONE: $name vuoto in $ENV_FILE, salto" >&2
      continue
    fi
    gc secrets describe "$name" >/dev/null 2>&1 || gc secrets create "$name" --replication-policy automatic
    # Nuova versione solo se il valore è cambiato (le versioni attive oltre la quota gratuita si pagano).
    if [ "$(gc secrets versions access latest --secret "$name" 2>/dev/null || true)" = "$value" ]; then
      echo "Segreto $name invariato."
      continue
    fi
    # Il valore passa da stdin: non compare nella riga di comando né nella cronologia.
    printf '%s' "$value" | gc secrets versions add "$name" --data-file=- >/dev/null
    echo "Segreto $name aggiornato."
  done
}

write_env_yaml() {
  local file="$1"
  : > "$file"
  for name in "${PLAIN_VARS[@]}"; do
    value="$(env_value "$name")"
    [ -n "$value" ] && printf '%s: "%s"\n' "$name" "${value//\"/\\\"}" >> "$file"
  done
  return 0
}

cmd_deploy() {
  local envfile secrets_flag="" image
  envfile="$(mktemp)"
  write_env_yaml "$envfile"
  # Collega solo i segreti presenti; quelli facoltativi possono mancare.
  for name in "${SECRETS[@]}"; do
    if gc secrets versions describe latest --secret "$name" >/dev/null 2>&1; then
      secrets_flag+="${name}=${name}:latest,"
    elif [[ "$OPTIONAL_SECRETS" != *" $name "* ]]; then
      echo "Manca il segreto $name: compilalo nel $ENV_FILE e lancia prima '$0 secrets'." >&2
      rm -f "$envfile"
      exit 1
    else
      echo "$name assente (facoltativo): funzione relativa disattivata." >&2
    fi
  done
  secrets_flag="${secrets_flag%,}"   # es. WHATSAPP_TOKEN=WHATSAPP_TOKEN:latest,…

  # Webhook: pubblico (Meta deve raggiungerlo; ogni richiesta è verificata con la firma X-Hub-Signature-256).
  # CPU sempre allocata: la foto si elabora dopo aver risposto 200 a Meta. Scala a zero quando non lo usi.
  gc run deploy "$SERVICE" --source . --region "$REGION" \
    --service-account "$RUNTIME_SA" --allow-unauthenticated \
    --no-cpu-throttling --min-instances 0 --max-instances 1 --cpu 1 --memory 512Mi --timeout 120 \
    --env-vars-file "$envfile" --set-secrets "$secrets_flag"

  # Il job usa la stessa immagine appena costruita.
  image="$(gc run services describe "$SERVICE" --region "$REGION" \
    --format 'value(spec.template.spec.containers[0].image)')"
  gc run jobs deploy "$JOB" --image "$image" --region "$REGION" --args job \
    --service-account "$RUNTIME_SA" --cpu 1 --memory 1Gi --task-timeout 15m --max-retries 1 \
    --env-vars-file "$envfile" --set-secrets "$secrets_flag"
  rm -f "$envfile"
  # Tiene solo le ultime 2 immagini nel repository creato da "run deploy --source" (quota gratuita: 0,5 GB).
  gc artifacts repositories set-cleanup-policies cloud-run-source-deploy --location "$REGION" \
    --policy deploy/artifact-cleanup.json --no-dry-run >/dev/null \
    || echo "ATTENZIONE: regola di pulizia delle immagini non impostata" >&2
  cmd_url
}

cmd_schedule() {
  local uri="https://run.googleapis.com/v2/projects/${PROJECT_ID}/locations/${REGION}/jobs/${JOB}:run"
  gc run jobs add-iam-policy-binding "$JOB" --region "$REGION" \
    --member "serviceAccount:${SCHEDULER_SA}" --role roles/run.invoker >/dev/null
  if gc scheduler jobs describe "${JOB}-daily" --location "$REGION" >/dev/null 2>&1; then
    action=update
  else
    action=create
  fi
  gc scheduler jobs "$action" http "${JOB}-daily" --location "$REGION" \
    --schedule "$SCHEDULE" --time-zone "$TIME_ZONE" --uri "$uri" --http-method POST \
    --oauth-service-account-email "$SCHEDULER_SA"
  echo "Job pianificato: '$SCHEDULE' ($TIME_ZONE). Per provarlo subito:"
  echo "  gcloud --project $PROJECT_ID run jobs execute $JOB --region $REGION --wait"
}

cmd_url() {
  local url
  url="$(gc run services describe "$SERVICE" --region "$REGION" --format 'value(status.url)')"
  echo "Callback URL per Meta: ${url}/webhook"
}

case "${1:-}" in
  setup) cmd_setup ;;
  secrets) cmd_secrets ;;
  deploy) cmd_deploy ;;
  schedule) cmd_schedule ;;
  url) cmd_url ;;
  all) cmd_setup; cmd_secrets; cmd_deploy; cmd_schedule ;;
  *) sed -n '2,10p' "$0"; exit 1 ;;
esac
