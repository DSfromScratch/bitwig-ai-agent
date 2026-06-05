#!/usr/bin/env bash
# Batch-Ingest aller Polarity-Projekte in Neo4j.
# Voraussetzung: Embedding-Server läuft (make embed-server)
#
# Ablauf pro Projekt:
#   1. Skript zeigt Projekt-Namen
#   2. Du öffnest das Projekt in Bitwig
#   3. Du drückst Enter
#   4. Ingest läuft automatisch

set -euo pipefail
cd "$(dirname "$0")/.."

PYTHON=".venv/bin/python"
EMBED_URL="http://127.0.0.1:8080"

PROJECTS=(
  "BitStep"
  "Clash"
  "Domination"
  "Elementos"
  "FutureGarageVoiceDraft1"
  "FutureGarageVoiceDraft2"
  "GenericHouse"
  "gridnik"
  "IntimateBounce"
  "new-york"
  "Ozoner"
  "StrangerThings"
  "SomeChords"
  "dnb-stream1"
  "Sunday"
  "Psytrance"
)

# Embedding-Server prüfen
if ! curl -sf "$EMBED_URL/health" > /dev/null 2>&1; then
  echo "❌  Embedding-Server nicht erreichbar ($EMBED_URL)"
  echo "    Starte ihn mit: make embed-server"
  exit 1
fi

echo "✅  Embedding-Server bereit"
echo "=============================="
echo " Batch-Ingest: ${#PROJECTS[@]} Projekte"
echo "=============================="
echo ""

DONE=0
FAILED=0
SKIPPED=0

for PROJECT in "${PROJECTS[@]}"; do
  echo "──────────────────────────────────────"
  echo "  Projekt: $PROJECT"
  echo "──────────────────────────────────────"
  echo "  → Öffne in Bitwig (Mac): /Users/sija/Documents/Bitwig Studio/Projects/polarity/$PROJECT"
  echo ""
  read -rp "  [Enter] wenn Projekt geladen, [s] überspringen, [q] abbrechen: " choice

  case "$choice" in
    q|Q)
      echo "Abgebrochen."
      break
      ;;
    s|S)
      echo "  ⏭  Übersprungen"
      SKIPPED=$((SKIPPED + 1))
      continue
      ;;
  esac

  echo "  🔄  Ingeste $PROJECT …"
  if $PYTHON scripts/ingest_live_project.py --project "$PROJECT" 2>&1; then
    echo "  ✅  $PROJECT fertig"
    DONE=$((DONE + 1))
  else
    echo "  ❌  $PROJECT fehlgeschlagen"
    FAILED=$((FAILED + 1))
  fi
  echo ""
done

echo "=============================="
echo " Fertig: $DONE ✅  |  $FAILED ❌  |  $SKIPPED ⏭"
echo "=============================="
