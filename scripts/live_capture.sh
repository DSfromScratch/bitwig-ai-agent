#!/usr/bin/env bash
# scripts/live_capture.sh
# Bündelt die wichtigsten Artefakte eines Live-Agent-Runs in einen Snapshot-Ordner.
# Aufruf:  ./scripts/live_capture.sh "kurzer-titel"
#
# Erzeugt:  BitwigTracks/sessions/<timestamp>__<titel>/
#           ├── agent.log              (Kopie von logs/agent_*.log, letzte 2000 Zeilen)
#           ├── generation_events.jsonl
#           ├── policy_feedback/       (falls vorhanden)
#           ├── env_snapshot.txt       (Git-Hash, Python-Version, ENV-Vars ohne Secrets)
#           └── README.md              (Vorlage für LIVE_LOG.md-Eintrag)

set -euo pipefail

cd "$(dirname "$0")/.."
ROOT="$(pwd)"

TITLE="${1:-untitled}"
TITLE_SAFE="$(echo "$TITLE" | tr ' /' '__' | tr -cd '[:alnum:]_-')"
STAMP="$(date +%Y%m%d_%H%M%S)"
OUT="BitwigTracks/sessions/${STAMP}__${TITLE_SAFE}"

mkdir -p "$OUT"

# Aktuellstes Agent-Log
LATEST_LOG="$(ls -t logs/agent_*.log 2>/dev/null | head -n1 || true)"
if [[ -n "$LATEST_LOG" ]]; then
  tail -n 2000 "$LATEST_LOG" > "$OUT/agent.log"
  echo "✓ agent.log (Quelle: $LATEST_LOG, letzte 2000 Zeilen)"
fi

# Generation events
if [[ -f logs/generation_events.jsonl ]]; then
  cp logs/generation_events.jsonl "$OUT/generation_events.jsonl"
  echo "✓ generation_events.jsonl"
fi

# Policy feedback
if [[ -d logs/policy_feedback ]]; then
  cp -R logs/policy_feedback "$OUT/policy_feedback"
  echo "✓ policy_feedback/"
fi

# Umgebungs-Snapshot (OHNE Secrets!)
{
  echo "# Environment Snapshot — $STAMP"
  echo
  echo "## Git"
  git --no-pager log -1 --oneline
  echo "Branch: $(git rev-parse --abbrev-ref HEAD)"
  echo "Uncommitted:"
  git status --short || true
  echo
  echo "## Python"
  python --version 2>&1 || true
  echo
  echo "## Relevante ENV-Variablen (Werte maskiert)"
  for v in NEO4J_URI NEO4J_USER VLLM_BASE_URL EMBEDDING_BASE_URL OSC_HOST OSC_PORT; do
    val="${!v:-}"
    [[ -n "$val" ]] && echo "$v=$val"
  done
  echo
  echo "Secrets vorhanden (nicht angezeigt):"
  for v in NEO4J_PASSWORD HF_TOKEN FREESOUND_API_KEY OPENAI_API_KEY; do
    [[ -n "${!v:-}" ]] && echo "  - $v: ✓"
  done
} > "$OUT/env_snapshot.txt"
echo "✓ env_snapshot.txt"

# Eintragsvorlage
cat > "$OUT/README.md" <<EOF
# Session $STAMP — $TITLE

**Setup:**
**Dauer:**

## Ablauf
- [ ] …

## ✅ Was hat funktioniert
- …

## ⚠️ Probleme / Bugs
| # | Symptom | Hypothese | Repro? | Komponente | Severity |
|---|---------|-----------|--------|------------|----------|
| 1 | … | … | y/n | \`src/…\` | P1 |

## 💡 Ideen
- …
EOF

echo
echo "📦 Snapshot: $OUT"
echo "→ Erkenntnisse in $ROOT/LIVE_LOG.md übertragen (neueste oben)."
