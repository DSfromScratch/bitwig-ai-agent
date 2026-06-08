"""
RL-Trainingsschleife: generieren → bewerten → DPO-trainieren → evaluieren.
Stoppt automatisch wenn avg_reward >= REWARD_THRESHOLD (statt fixer Iterationen).

Run: python scripts/rl_train_loop.py [--rounds N] [--reward-threshold 0.85]
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from dotenv import load_dotenv
load_dotenv()

import requests

# ── Konfiguration ─────────────────────────────────────────────────────────────
MAC_HOST          = os.getenv("MAC_HOST", "192.168.0.4")  # nur für Remote (SSH/rsync)
MAC_USER          = "sija"
MAC_DATA_DIR      = os.getenv("MLX_DATA_DIR", "/Users/sija/mlx-dpo-data")
MAC_ADAPTER_DIR   = os.getenv("MLX_ADAPTER_DIR", "/Users/sija/mlx-server/models/adapter")
MODEL_PATH        = os.getenv("MLX_BASE_MODEL", "/Users/sija/mlx-server/models/base")
MLX_PYTHON        = os.getenv("MLX_PYTHON", "/Users/sija/.venv-mlx/bin/python")

LOCAL_DATA_DIR    = "./training_data"
# Der MLX-Server läuft als lokaler LaunchAgent. Standardmäßig über localhost
# verbinden (Loopback ist stabil; die LAN-IP kann nach DHCP-Wechsel/Restart
# unerreichbar sein). Für echtes Remote-Training via MLX_CONNECT_HOST override.
MLX_CONNECT_HOST  = os.getenv("MLX_CONNECT_HOST", "localhost")
MLX_URL           = f"http://{MLX_CONNECT_HOST}:8080/v1/chat/completions"  # Fine-tuned (LaunchAgent)
MODEL_ID          = "mlx-community/Qwen3-8B-4bit"

REWARD_THRESHOLD  = 0.82    # Stoppt wenn avg_reward hier
DPO_ITERS_PER_ROUND = 100   # DPO-Steps pro Runde (klein halten)
MAX_ROUNDS        = 10

SYSTEM_PROMPT = """/no_think
Du bist ein Bitwig Studio AI-Assistent. Verfügbare Tools:
- get_song_context(project_name) → Tempo, Szenen, Energie-Level, Track-Rollen
- create_track_from_recipe(track_name, project_name, scene_name, include_notes, include_params)
- reconstruct_project(project_name, include_notes, include_params, dry_run)
- write_pattern(track_name, notes, length_beats, key, append)
- scan_and_learn_project()

Bekannte Projekte: "Chee - Hey Now"
Bekannte Szenen: "Intro", "Raise", "Garage", "Peak", "Break", "Trap", "Impro", "Outro"
Szenen-Energie: Intro=spärlich(33%), Peak/Break=voll(95-100%)

notes MUSS eine Liste von max 32 Dicts sein:
[{"step": 0, "pitch": 60, "velocity": 80, "duration": 0.4}, ...]
Niemals notes als String oder Notennamen ausgeben.

Tonarten (Deutsch→Englisch): C-Moll=C minor, D-Moll=D minor, E-Moll=E minor,
F-Moll=F minor, G-Moll=G minor, A-Moll=A minor, H-Moll=B minor,
Cis-Moll=C# minor, Dis-Moll=D# minor, Fis-Moll=F# minor, Gis-Moll=G# minor,
B-Moll=Bb minor, C-Dur=C major, D-Dur=D major, E-Dur=E major.

Antworte NUR mit einem JSON Tool-Aufruf im Format:
{"tool": "<name>", "args": {<parameter>}}"""

EVAL_PROMPTS = [
    # ── Bekannte Projekt-Prompts (sollten immer 1.0 sein) ─────────────────────
    "Erstelle einen Pad-Sound ähnlich wie Dissonant Pad aus Chee - Hey Now",
    "Rekonstruiere das komplette Projekt Chee - Hey Now",
    "Füge den Sharp Arp Track aus der Break-Szene ein",
    "Füge einen Sine Pluck 1 Sound ein wie in Chee - Hey Now",
    "Lerne das aktuelle Bitwig-Projekt kennen.",
    # ── write_pattern: Skala-Patterns (notes als Liste, key korrekt) ──────────
    "Schreibe ein MIDI-Pattern für Sine Pluck 1 in C-Moll, 8 Beats",
    "Schreibe ein Arpeggio-Pattern in Fis-Moll, 4 Beats",
    "G-Dur aufsteigendes Pattern, 8 Beats, für einen Synth-Track.",
    # ── Akkordfolgen (notes mit mehreren Pitches pro Step) ────────────────────
    "Schreibe eine i-iv-v-i Akkordfolge in A-Moll, 8 Beats.",
    "Schreibe eine I-IV-V-I Akkordfolge in C-Dur, 8 Beats für Chord-Track.",
    # ── Schwierige Paraphrasierungen ─────────────────────────────────────────
    "Mach einen Sound wie der scharfe Arpeggiator aus dem Break-Teil von Hey Now.",
    "Baue Chee Hey Now in Bitwig nach — komplett mit Parametern.",
    # ── Polarity-Projekte (nach Ingest 1.0, davor 0.75 — gibt Trainingssignal)
    "Füge den Bassline-Track aus dem Clash Projekt ein.",
    "Rekonstruiere das GenericHouse Projekt.",
    "Schreibe ein Psytrance-Pattern in E-Moll, 8 Beats.",
]


def _eval_prompts_with_neo4j(extra_anchors: int = 8,
                              per_anchor: int = 1) -> list[str]:
    """Kombiniert die statischen EVAL_PROMPTS mit dynamischen Stil-Prompts
    aus den (:Song)-Knoten in Neo4j. Wenn Neo4j down ist, fällt es leise
    auf die statische Liste zurück."""
    try:
        from scripts._neo4j_song_prompts import load_prompts
        extras = load_prompts(limit=extra_anchors, n_per_song=per_anchor, seed=0)
    except Exception:
        extras = []
    return list(EVAL_PROMPTS) + extras


# ── Evaluierung ───────────────────────────────────────────────────────────────

def evaluate(model_url: str, temperature: float = 0.0,
             prompts: list[str] | None = None,
             threshold: float = REWARD_THRESHOLD,
             max_retries: int = 3) -> float:
    """Berechnet avg_reward auf den Eval-Prompts.

    Robust gegen Server-Crashes: Auf dem 16-GB-Mac kann der MLX-Server bei
    langen Generierungen abstürzen (OOM) und wird vom LaunchAgent neu
    gestartet. Timeouts/Connection-Fehler werden daher mit Backoff bis zu
    `max_retries` mal wiederholt, statt den Prompt mit 0.0 zu werten.
    """
    from src.agent.tools.music.reward import score_completion

    eval_set = prompts if prompts is not None else _eval_prompts_with_neo4j()
    scores = []
    for prompt in eval_set:
        score: float | None = None
        for attempt in range(1, max_retries + 1):
            try:
                r = requests.post(model_url, json={
                    "model":       MODEL_ID,
                    "messages": [
                        {"role": "system", "content": SYSTEM_PROMPT},
                        {"role": "user",   "content": prompt},
                    ],
                    "max_tokens":  1200,
                    "temperature": temperature,
                }, timeout=120)
                if r.status_code == 200:
                    content = r.json()["choices"][0]["message"].get("content", "")
                    score, _ = score_completion(prompt, content)
                    break
                print(f"  ⚠ HTTP {r.status_code} (Versuch {attempt}/{max_retries})")
            except Exception as e:
                print(f"  ⚠ {type(e).__name__} (Versuch {attempt}/{max_retries}): {str(e)[:80]}")
            if attempt < max_retries:
                # Server-Restart abwarten (LaunchAgent braucht ein paar Sekunden)
                time.sleep(8 * attempt)

        s = score if score is not None else 0.0
        scores.append(s)
        print(f"  {s:.2f}  {prompt[:55]}…")

    avg = sum(scores) / len(scores) if scores else 0.0
    print(f"  ─── avg_reward = {avg:.3f} ({'✅ Ziel erreicht!' if avg >= threshold else '🔄 weiter trainieren'})")
    return avg


# ── SSH-Helfer ────────────────────────────────────────────────────────────────

def _local_ips() -> set[str]:
    ips = {"127.0.0.1", "localhost"}
    try:
        out = subprocess.run(["ifconfig"], capture_output=True, text=True, check=False).stdout
        for line in out.splitlines():
            line = line.strip()
            if line.startswith("inet ") and "127.0.0.1" not in line:
                ips.add(line.split()[1])
    except Exception:
        pass
    return ips


# LOCAL_MODE: kein SSH/rsync, alles lokal. True wenn MAC_HOST eine lokale IP
# ist, explizit per RL_LOCAL_MODE=1 erzwungen, ODER der MLX-Server lokal auf
# localhost:8080 erreichbar ist (robust gegen DHCP-IP-Wechsel).
def _mlx_local_reachable() -> bool:
    try:
        requests.get("http://localhost:8080/v1/models", timeout=2)
        return True
    except Exception:
        return False


_LOCAL_MODE = (
    MAC_HOST in _local_ips()
    or os.getenv("RL_LOCAL_MODE") == "1"
    or _mlx_local_reachable()
)


def _ssh(cmd: str) -> int:
    if _LOCAL_MODE:
        # stdin=DEVNULL: verhindert "init_sys_streams: Bad file descriptor"-Crashes
        # frisch gestarteter Python-Subprozesse, wenn der Loop selbst im
        # Hintergrund (nohup, ohne TTY) läuft.
        return subprocess.run(
            ["bash", "-lc", cmd], check=False, stdin=subprocess.DEVNULL
        ).returncode
    result = subprocess.run(
        ["ssh", f"{MAC_USER}@{MAC_HOST}", cmd],
        check=False,
        stdin=subprocess.DEVNULL,
    )
    return result.returncode


def _rsync_to_mac(local: str, remote: str) -> None:
    if _LOCAL_MODE:
        import shutil
        if os.path.abspath(local) == os.path.abspath(remote):
            return
        os.makedirs(os.path.dirname(remote) or ".", exist_ok=True)
        shutil.copy(local, remote)
        return
    subprocess.run([
        "rsync", "-az", "--progress",
        local,
        f"{MAC_USER}@{MAC_HOST}:{remote}",
    ], check=True)


# ── DPO-Training auf Mac ──────────────────────────────────────────────────────

_CONVERTER_SCRIPT = '''
import json, pathlib, sys

data_dir = pathlib.Path(sys.argv[1] if len(sys.argv) > 1 else ".")

def convert(dpo_path: pathlib.Path, sft_path: pathlib.Path) -> int:
    rows = [json.loads(l) for l in dpo_path.read_text().splitlines() if l.strip()]
    with sft_path.open("w") as f:
        for r in rows:
            user = r.get("user_message") or r.get("prompt", "").rsplit("\\n\\n", 1)[-1].strip()
            ex = {"messages": [
                {"role": "user",      "content": user},
                {"role": "assistant", "content": r["chosen"]},
            ]}
            f.write(json.dumps(ex, ensure_ascii=False) + "\\n")
    return len(rows)

n_train = convert(data_dir / "dpo_train.jsonl", data_dir / "train.jsonl")
n_valid = convert(data_dir / "dpo_valid.jsonl", data_dir / "valid.jsonl")
print(f"✅ Konvertiert: {n_train} Train + {n_valid} Valid Beispiele (chosen-only SFT)")
'''


def _deploy_converter() -> None:
    """Schreibt das DPO→SFT Konvertierungs-Skript auf den Mac (oder lokal)."""
    if _LOCAL_MODE:
        os.makedirs(MAC_DATA_DIR, exist_ok=True)
        with open(os.path.join(MAC_DATA_DIR, "dpo_to_sft.py"), "w") as f:
            f.write(_CONVERTER_SCRIPT)
        return
    import tempfile
    with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False) as tmp:
        tmp.write(_CONVERTER_SCRIPT)
        tmp_path = tmp.name
    subprocess.run([
        "scp", tmp_path,
        f"{MAC_USER}@{MAC_HOST}:{MAC_DATA_DIR}/dpo_to_sft.py",
    ], check=True, capture_output=True)
    os.unlink(tmp_path)


_LAUNCH_AGENT = os.path.expanduser(
    "~/Library/LaunchAgents/com.bitwigagent.mlxserver.plist")


def _stop_mlx_server() -> None:
    """Stoppt den MLX-Server. Im lokalen Modus wird der KeepAlive-LaunchAgent
    entladen, sonst startet er den Server mitten im Training neu (Kernel-Panic)."""
    if _LOCAL_MODE and os.path.exists(_LAUNCH_AGENT):
        print("🛑 LaunchAgent entladen (verhindert Auto-Restart während Training)…")
        subprocess.run(["launchctl", "unload", _LAUNCH_AGENT], check=False)
    _ssh("kill $(lsof -ti:8080) 2>/dev/null; sleep 3; echo 'Server gestoppt'")


def _start_mlx_server_local() -> bool:
    """Lädt den LaunchAgent wieder (serviert den frisch trainierten Adapter,
    da er auf denselben adapter-path zeigt)."""
    if _LOCAL_MODE and os.path.exists(_LAUNCH_AGENT):
        print("🔄 LaunchAgent laden (serviert neuen Adapter)…")
        subprocess.run(["launchctl", "load", _LAUNCH_AGENT], check=False)
        for _ in range(30):
            try:
                r = requests.get(f"http://{MAC_HOST}:8080/v1/models", timeout=3)
                if r.status_code == 200:
                    print("  ✅ Server bereit")
                    return True
            except Exception:
                pass
            time.sleep(2)
        print("⚠ Server nicht erreichbar nach 60s")
        return False
    return False


def train_dpo_on_mac(round_num: int) -> bool:
    """
    Überträgt DPO-Paare, konvertiert sie zu SFT (chosen-only) und
    startet LoRA-Training mit --mask-prompt auf Mac.
    WICHTIG: Beide MLX-Server werden VOR dem Training gestoppt, um
    Kernel Panics durch GPU-Memory-Overflow zu vermeiden.
    """
    print(f"\n📤 Sende DPO-Daten zum Mac…")
    _ssh(f"mkdir -p {MAC_DATA_DIR}")
    _rsync_to_mac(f"{LOCAL_DATA_DIR}/dpo_train.jsonl", f"{MAC_DATA_DIR}/dpo_train.jsonl")
    _rsync_to_mac(f"{LOCAL_DATA_DIR}/dpo_valid.jsonl", f"{MAC_DATA_DIR}/dpo_valid.jsonl")

    # ── GPU-RAM freigeben: MLX-Server stoppen ────────────────────────────────
    print("🛑 MLX-Server stoppen (GPU-RAM freigeben)…")
    _stop_mlx_server()

    # Konvertierungs-Skript auf Mac ablegen und ausführen
    _deploy_converter()
    rc = _ssh(f"{MLX_PYTHON} {MAC_DATA_DIR}/dpo_to_sft.py {MAC_DATA_DIR}")
    if rc != 0:
        print("⚠ Konvertierung fehlgeschlagen")
        _start_mlx_server_local()
        return False

    # Bestehenden Adapter fortsetzen, falls vorhanden (Live-Adapter weitertrainieren)
    resume = ""
    existing = os.path.join(MAC_ADAPTER_DIR, "adapters.safetensors")
    if _LOCAL_MODE and os.path.exists(existing):
        resume = f"--resume-adapter-file {existing} "
        print(f"↩ Setze bestehenden Adapter fort: {existing}")

    train_cmd = (
        f"{MLX_PYTHON} -m mlx_lm lora "
        f"--model {MODEL_PATH} "
        f"--adapter-path {MAC_ADAPTER_DIR} "
        f"{resume}"
        f"--train "
        f"--fine-tune-type lora "
        f"--data {MAC_DATA_DIR} "
        f"--mask-prompt "
        f"--iters {DPO_ITERS_PER_ROUND} "
        f"--batch-size 1 "
        f"--max-seq-length 512 "
        f"--grad-checkpoint "
        f"--learning-rate 5e-5 "
        f"--save-every {DPO_ITERS_PER_ROUND} "
        f"> /tmp/mlx_dpo_round_{round_num}.log 2>&1"
    )

    print(f"🏋 LoRA-Training (chosen-only) Runde {round_num} ({DPO_ITERS_PER_ROUND} Steps)…")
    rc = _ssh(train_cmd)
    if rc != 0:
        print(f"⚠ Training fehlgeschlagen (exit {rc}) — Log:")
        _ssh(f"tail -30 /tmp/mlx_dpo_round_{round_num}.log")
        _start_mlx_server_local()
        return False

    # ── Fine-tuned Server neu starten (Port 8080, mit neuem Adapter) ─────────
    print("🔄 Fine-tuned Server (8080) neu starten…")
    if _LOCAL_MODE and os.path.exists(_LAUNCH_AGENT):
        # LaunchAgent serviert denselben adapter-path → lädt frischen Adapter
        return _start_mlx_server_local()
    _ssh(f"nohup {MLX_PYTHON} -m mlx_lm.server "
         f"--model {MODEL_PATH} "
         f"--adapter-path {MAC_ADAPTER_DIR} "
         f"--port 8080 --host 0.0.0.0 "
         f"> /tmp/mlx_8080.log 2>&1 &")

    # Warten bis Server bereit
    print("⏳ Warte auf Server…")
    for _ in range(30):
        try:
            r = requests.get(f"http://{MAC_HOST}:8080/v1/models", timeout=3)
            if r.status_code == 200:
                print("  ✅ Server bereit")
                return True
        except Exception:
            pass
        time.sleep(2)

    print("⚠ Server nicht erreichbar nach 60s")
    return False


# ── Haupt-Loop ────────────────────────────────────────────────────────────────

def rl_loop(max_rounds: int = MAX_ROUNDS, reward_threshold: float = REWARD_THRESHOLD) -> None:
    from scripts.generate_dpo_pairs import generate_pairs

    print("=" * 65)
    print("RL-TRAINING: Bitwig-Agent (DPO, Reward-basiert)")
    print(f"Ziel: avg_reward ≥ {reward_threshold} | max {max_rounds} Runden")
    print("=" * 65)

    history: list[dict] = []

    for rnd in range(1, max_rounds + 1):
        print(f"\n{'─' * 65}")
        print(f"RUNDE {rnd}/{max_rounds}")
        print(f"{'─' * 65}")

        # ── Schritt 1: DPO-Paare generieren ──────────────────────────────────
        print("\n① DPO-Paare generieren…")
        stats = generate_pairs(
            model_url=MLX_URL,
            data_dir=LOCAL_DATA_DIR,
            max_prompts=40,
        )
        if stats.get("pairs_generated", 0) < 4:
            print("⚠ Zu wenige Paare — Runde übersprungen")
            continue

        # ── Schritt 2: Auf Mac trainieren ─────────────────────────────────────
        print("\n② DPO-Training auf Mac…")
        ok = train_dpo_on_mac(rnd)
        if not ok:
            print("⚠ Training fehlgeschlagen — Abbruch")
            break

        # ── Schritt 3: Evaluieren ─────────────────────────────────────────────
        print(f"\n③ Evaluierung (Fine-tuned, Runde {rnd})…")
        avg_reward = evaluate(MLX_URL, threshold=reward_threshold)

        history.append({
            "round":        rnd,
            "pairs":        stats["pairs_generated"],
            "avg_reward":   avg_reward,
            "dpo_iters":    DPO_ITERS_PER_ROUND,
        })

        # Checkpoint
        ckpt_path = f"{LOCAL_DATA_DIR}/rl_history.json"
        with open(ckpt_path, "w") as f:
            json.dump(history, f, indent=2)

        if avg_reward >= reward_threshold:
            print(f"\n🎉 FERTIG! avg_reward={avg_reward:.3f} ≥ {reward_threshold}")
            print(f"   Adapter: {MAC_ADAPTER_DIR}/adapters.safetensors")
            break

    print(f"\n{'=' * 65}")
    print("ZUSAMMENFASSUNG")
    for h in history:
        print(f"  Runde {h['round']}: avg_reward={h['avg_reward']:.3f}  Paare={h['pairs']}")
    print("=" * 65)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--rounds",           type=int,   default=MAX_ROUNDS)
    parser.add_argument("--reward-threshold", type=float, default=REWARD_THRESHOLD)
    args = parser.parse_args()
    rl_loop(max_rounds=args.rounds, reward_threshold=args.reward_threshold)
