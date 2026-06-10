#!/usr/bin/env bash
# Richtet die QLoRA-Trainingsumgebung auf einer Linux GPU-Maschine ein.
# Getestet mit NVIDIA 16GB VRAM + Python 3.11/3.12, Ubuntu 22.04+.
#
# Verwendung:
#   chmod +x scripts/setup_linux.sh
#   ./scripts/setup_linux.sh [--skip-torch] [--no-unsloth]
set -euo pipefail

# ── Optionen ─────────────────────────────────────────────────────────────────
SKIP_TORCH=0
NO_UNSLOTH=0
for arg in "$@"; do
    case $arg in
        --skip-torch)  SKIP_TORCH=1 ;;
        --no-unsloth)  NO_UNSLOTH=1 ;;
    esac
done

# ── Hilfsfunktionen ───────────────────────────────────────────────────────────
log()  { echo "[$(date '+%H:%M:%S')] $*"; }
ok()   { echo "[$(date '+%H:%M:%S')] ✓ $*"; }
warn() { echo "[$(date '+%H:%M:%S')] ⚠ $*"; }
fail() { echo "[$(date '+%H:%M:%S')] ✗ $*" >&2; exit 1; }

# ── Python-Venv anlegen ───────────────────────────────────────────────────────
VENV="${TRAIN_VENV:-$HOME/.venv-train}"
PYTHON="${PYTHON:-python3}"

$PYTHON --version >/dev/null 2>&1 || fail "python3 nicht gefunden — bitte installieren"

if [ ! -d "$VENV" ]; then
    log "Erstelle venv: $VENV"
    $PYTHON -m venv "$VENV"
fi
# shellcheck disable=SC1091
source "$VENV/bin/activate"
ok "venv aktiv: $VENV"

# ── CUDA-Version erkennen ─────────────────────────────────────────────────────
CUDA_VER=""
if command -v nvcc &>/dev/null; then
    CUDA_VER=$(nvcc --version 2>/dev/null | grep "release" | awk '{print $5}' | tr -d ,)
fi
if [ -z "$CUDA_VER" ] && command -v nvidia-smi &>/dev/null; then
    CUDA_VER=$(nvidia-smi --query-gpu=driver_version --format=csv,noheader 2>/dev/null | head -1 || true)
fi
if [ -z "$CUDA_VER" ]; then
    warn "CUDA nicht erkannt — PyTorch-CPU-Fallback"
    TORCH_EXTRA=""
else
    log "CUDA erkannt: $CUDA_VER"
    # CUDA 12.x → cu121, CUDA 11.8 → cu118
    if [[ "$CUDA_VER" == 12* ]]; then
        TORCH_EXTRA="--index-url https://download.pytorch.org/whl/cu121"
    else
        TORCH_EXTRA="--index-url https://download.pytorch.org/whl/cu118"
    fi
fi

# ── PyTorch installieren ──────────────────────────────────────────────────────
if [ "$SKIP_TORCH" -eq 0 ]; then
    log "Installiere PyTorch..."
    # shellcheck disable=SC2086
    pip install torch torchvision $TORCH_EXTRA --quiet
    ok "PyTorch installiert"
fi

# ── Core-Training-Pakete ──────────────────────────────────────────────────────
log "Installiere HuggingFace + TRL + PEFT + BitsAndBytes..."
pip install --quiet \
    transformers>=4.45.0 \
    accelerate>=0.30.0 \
    peft>=0.11.0 \
    bitsandbytes>=0.43.0 \
    trl>=0.9.0 \
    datasets>=2.20.0 \
    huggingface-hub>=0.24.0 \
    sentencepiece \
    protobuf \
    einops
ok "Core-Pakete installiert"

# ── Unsloth (optional, 2× Speedup) ───────────────────────────────────────────
if [ "$NO_UNSLOTH" -eq 0 ]; then
    log "Installiere Unsloth (schnelleres QLoRA-Training)..."
    # Unsloth muss nach torch installiert werden
    TORCH_INSTALLED=$(python -c "import torch; print(torch.__version__.split('+')[0])" 2>/dev/null || echo "")
    if [ -n "$TORCH_INSTALLED" ]; then
        pip install "unsloth[colab-new]" --quiet || {
            warn "Unsloth konnte nicht installiert werden — Standard-QLoRA wird verwendet"
        }
    else
        warn "PyTorch nicht gefunden — Unsloth übersprungen"
    fi
fi

# ── Optionale Utilities ───────────────────────────────────────────────────────
log "Installiere Utilities..."
pip install --quiet \
    wandb \
    tensorboard \
    tqdm \
    python-dotenv
ok "Utilities installiert"

# ── Adapter-Verzeichnis anlegen ───────────────────────────────────────────────
ADAPTER_DIR="${TRAIN_ADAPTER_DIR:-./adapters/bitwig-agent}"
mkdir -p "$ADAPTER_DIR"
ok "Adapter-Verzeichnis: $ADAPTER_DIR"

# ── GPU-Info ausgeben ─────────────────────────────────────────────────────────
if command -v nvidia-smi &>/dev/null; then
    echo ""
    log "GPU-Status:"
    nvidia-smi --query-gpu=name,memory.total,memory.free --format=csv,noheader | \
        while IFS=, read -r name total free; do
            echo "  $name | Total: $total | Frei: $free"
        done
fi

# ── Installations-Test ────────────────────────────────────────────────────────
log "Prüfe Installation..."
python - <<'EOF'
import sys
failed = []
try:
    import torch
    print(f"  PyTorch:        {torch.__version__} | CUDA: {torch.cuda.is_available()}")
except ImportError:
    failed.append("torch")
try:
    import transformers
    print(f"  Transformers:   {transformers.__version__}")
except ImportError:
    failed.append("transformers")
try:
    import peft
    print(f"  PEFT:           {peft.__version__}")
except ImportError:
    failed.append("peft")
try:
    import bitsandbytes as bnb
    print(f"  BitsAndBytes:   {bnb.__version__}")
except ImportError:
    failed.append("bitsandbytes")
try:
    import trl
    print(f"  TRL:            {trl.__version__}")
except ImportError:
    failed.append("trl")
try:
    import unsloth  # noqa: F401
    print(f"  Unsloth:        ✓")
except ImportError:
    print(f"  Unsloth:        nicht installiert (Standard-QLoRA wird verwendet)")
if failed:
    print(f"FEHLER: Folgende Pakete fehlen: {', '.join(failed)}", file=sys.stderr)
    sys.exit(1)
EOF

echo ""
ok "Setup abgeschlossen!"
echo ""
echo "Training starten:"
echo "  source $VENV/bin/activate"
echo "  python scripts/train_linux.py --mode sft --iters 300"
echo ""
echo "Env-Vars überschreiben:"
echo "  TRAIN_BASE_MODEL=Qwen/Qwen3-14B python scripts/train_linux.py"
