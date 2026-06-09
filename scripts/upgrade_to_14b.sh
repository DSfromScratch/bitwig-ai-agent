#!/bin/bash
# Phase 1: Upgrade Mac MLX-Server von Qwen3-8B auf Qwen3-14B-4bit
#
# Voraussetzungen:
#   - mlx_lm installiert: pip install mlx-lm
#   - Mindestens 30GB freier Speicherplatz (Modell ~8GB)
#   - MLX-Server LaunchAgent läuft (com.bitwigagent.mlxserver)
#
# Ablauf:
#   1. Modell von HuggingFace herunterladen
#   2. LaunchAgent stoppen
#   3. Neues Modell als aktives Base-Modell setzen
#   4. LaunchAgent ohne Adapter neu starten (8B-Adapter inkompatibel mit 14B)
#
# Adapter-Hinweis:
#   Der vorhandene LoRA-Adapter (/Users/sija/mlx-server/models/adapter) wurde
#   für Qwen3-8B trainiert und ist mit 14B inkompatibel. Er wird vorübergehend
#   deaktiviert. Neues Adapter-Training läuft in Phase 5 (generate_dpo_pairs.py).

set -e

MODEL_DIR="/Users/sija/mlx-server/models"
TARGET_MODEL="mlx-community/Qwen3-14B-4bit"
TARGET_PATH="${MODEL_DIR}/Qwen3-14B-4bit"
BASE_LINK="${MODEL_DIR}/base"
PLIST="/Users/sija/Library/LaunchAgents/com.bitwigagent.mlxserver.plist"

echo "=== Qwen3-14B Upgrade ==="

# 1. Modell herunterladen
if [ -d "${TARGET_PATH}" ]; then
    echo "[OK] Modell bereits vorhanden: ${TARGET_PATH}"
else
    echo "[DL] Lade ${TARGET_MODEL} herunter..."
    python -c "
import subprocess, sys
subprocess.run([
    sys.executable, '-m', 'mlx_lm.convert',
    '--hf-path', '${TARGET_MODEL}',
    '--mlx-path', '${TARGET_PATH}',
], check=True)
"
    echo "[OK] Download abgeschlossen."
fi

# 2. LaunchAgent stoppen
echo "[--] Stoppe MLX-Server..."
launchctl unload "${PLIST}" 2>/dev/null || true
sleep 2

# 3. Base-Symlink auf 14B umstellen
if [ -L "${BASE_LINK}" ]; then
    OLD_TARGET=$(readlink "${BASE_LINK}")
    echo "[>>] base: ${OLD_TARGET} → Qwen3-14B-4bit"
    ln -sf "${TARGET_PATH}" "${BASE_LINK}"
elif [ -d "${BASE_LINK}" ]; then
    echo "[!!] ${BASE_LINK} ist ein Verzeichnis, kein Symlink."
    echo "     Benenne es um und erstelle Symlink:"
    mv "${BASE_LINK}" "${MODEL_DIR}/Qwen3-8B-4bit-backup"
    ln -sf "${TARGET_PATH}" "${BASE_LINK}"
fi

# 4. Plist aktualisieren: --adapter-path entfernen
echo "[>>] Aktualisiere LaunchAgent plist (Adapter deaktiviert)..."
python3 - <<'PYEOF'
import plistlib, shutil, os

plist_path = "/Users/sija/Library/LaunchAgents/com.bitwigagent.mlxserver.plist"
shutil.copy(plist_path, plist_path + ".bak")

with open(plist_path, "rb") as f:
    data = plistlib.load(f)

args = data.get("ProgramArguments", [])
# Adapter-Argumente entfernen
cleaned = []
skip_next = False
for arg in args:
    if skip_next:
        skip_next = False
        continue
    if arg == "--adapter-path":
        skip_next = True
        continue
    cleaned.append(arg)
data["ProgramArguments"] = cleaned

with open(plist_path, "wb") as f:
    plistlib.dump(data, f)

print(f"[OK] Plist aktualisiert. Backup: {plist_path}.bak")
print(f"[OK] ProgramArguments: {cleaned}")
PYEOF

# 5. LaunchAgent neu starten
echo "[>>] Starte MLX-Server mit Qwen3-14B..."
launchctl load "${PLIST}"
sleep 5

# 6. Health-Check
echo "[??] Health-Check..."
if curl -sf http://localhost:8080/v1/models | python3 -c "import sys,json; d=json.load(sys.stdin); print('[OK] Modell aktiv:', d['data'][0]['id'])" 2>/dev/null; then
    echo "=== Upgrade erfolgreich ==="
    echo "    Nächster Schritt: .env → LLM_BACKEND=mlx, MLX_MODEL=mlx-community/Qwen3-14B-4bit"
else
    echo "[!!] Server antwortet nicht. Prüfe: tail -f /Users/sija/mlx-server/logs/server-error.log"
    exit 1
fi
