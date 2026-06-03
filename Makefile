.DEFAULT_GOAL := help
JAVA_HOME ?= $(or $(wildcard $(HOME)/.sdkman/candidates/java/25.0.2-open),$(wildcard /usr/lib/jvm/java-25-openjdk),$(error JDK 25 nicht gefunden — JAVA_HOME setzen))
VENV     := .venv
PYTHON   := $(shell if [ -e "$(VENV)/bin/python" ] && "$(VENV)/bin/python" --version >/dev/null 2>&1; then printf '%s' "$(VENV)/bin/python"; elif command -v python3.11 >/dev/null 2>&1; then command -v python3.11; elif command -v python3 >/dev/null 2>&1; then command -v python3; else command -v python; fi)
UV       := $(shell command -v uv 2>/dev/null || echo $$HOME/.local/bin/uv)
STREAMLIT := $(PYTHON) -m streamlit
PYTEST   := $(PYTHON) -m pytest

FILE ?= song.mp3

# ── Mac Deploy Konfiguration ─────────────────────────────────────────────────
MAC_HOST     ?= 192.168.0.4
MAC_USER     ?= sija
MAC_EXT_DIR  := /Users/$(MAC_USER)/Documents/Bitwig Studio/Extensions
LOCAL_EXT_DIR := $(HOME)/Bitwig\ Studio/Extensions
LINUX_IP     := $(shell ip route get 1 2>/dev/null | awk '{print $$7; exit}')
EXT_DIST     := bitwig-extension/dist

.PHONY: help install download-mf dashboard embed-server agent start analyse validate test clean neo4j-import build-extension deploy-local deploy-mac deploy-mac-http deploy ssh-setup-mac test-integration test-neo4j test-all agent-service-install agent-service-start agent-service-stop agent-service-status agent-service-logs container-neo4j-start container-neo4j-stop container-neo4j-logs container-vllm-start container-vllm-stop container-vllm-logs container-vllm-build container-status mlx-export mlx-setup mlx-sync-data mlx-train mlx-test

help: ## Verfügbare Befehle anzeigen
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) \
		| awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-14s\033[0m %s\n", $$1, $$2}'

install: ## Abhängigkeiten installieren
	@if [ ! -d "$(VENV)" ]; then $(UV) python install 3.11 && $(UV) venv --python 3.11 $(VENV); fi
	$(UV) pip install --python $(PYTHON) -r requirements.txt

download-mf: ## Music Flamingo Modell herunterladen (~16 GB, einmalig)
	$(PYTHON) -c "\
from huggingface_hub import snapshot_download; \
print('Lade Music Flamingo FP8...'); \
snapshot_download('henry1477/music-flamingo-2601-hf-fp8'); \
print('Download abgeschlossen.')"

scan-vsts: ## Installierte VST-Plugins aus Bitwig scannen und in Neo4j speichern
	$(PYTHON) -c "from src.knowledge.vst_scanner import scan_and_store; print(scan_and_store())"

neo4j-import: ## Neo4j Graph aus Bitwig-Installation neu aufbauen
	$(PYTHON) -c "\
from src.knowledge.neo4j_graph import create_schema, build_graph; \
create_schema(); build_graph(); print('✓ Neo4j Graph aufgebaut')"

dashboard: ## Streamlit Dashboard starten
	$(STREAMLIT) run dashboard/app.py --server.port 8501

embed-server: ## Lokalen Embedding-Server starten (Port 8080, kein HF-Netzwerk)
	$(PYTHON) start_agent.py --embed-server-up

agent: ## Interaktiven CLI-Agent starten (vLLM nötig)
	@LD_LIBRARY_PATH=.cuda_compat:$(LD_LIBRARY_PATH) $(PYTHON) -m src.agent.core

start: ## 🚀 MCP Server + Agent starten (vollständiger Stack)
	$(PYTHON) start_agent.py

stack-up: ## Vollen Stack starten (Neo4j + vLLM + Agent)
	systemctl --user start neo4j.service vllm@agent.service
	$(PYTHON) start_agent.py

stack-down: ## Stack stoppen (Neo4j + vLLM)
	systemctl --user stop vllm@agent.service neo4j.service

stack-status: ## Stack-Status anzeigen
	@systemctl --user status neo4j.service vllm@agent.service --no-pager 2>/dev/null | grep -E '(●|○|Active|Main PID)'
	$(PYTHON) start_agent.py --status-only

analyse: ## Song analysieren: make analyse FILE=song.mp3
	$(PYTHON) -c "\
from src.agent.tools.analyse import analyse_audio; \
import json; \
r = analyse_audio.invoke({'file_path': '$(FILE)', 'separate_stems': True, 'extract_midi': True, 'send_osc': True}); \
print(json.dumps({k:v for k,v in r.items() if k not in ('energy_curve','quality')}, indent=2, ensure_ascii=False)); \
[print(f\"  {q['stem']:10s} {q['quality']}\") for q in r.get('quality',[])]"

validate: ## MIDI validieren: make validate GEN=melody.mid REF=bitwig.mid
	$(PYTHON) -c "\
from src.audio.midi_validate import validate, print; \
import json; \
r = validate('$(GEN)', '$(REF)', '$(or $(PNG),/tmp/validation.png)'); \
print(json.dumps({k:v for k,v in r.items() if k != 'plot'}, indent=2, ensure_ascii=False))"

test: ## Tests ausführen
	$(PYTEST) tests/ -q

test-integration: ## Integration-Tests ausführen (Mock-OSC, kein Bitwig nötig)
	BITWIG_TEST_MODE=mock $(PYTEST) tests/ -q -m "integration" --tb=short

test-neo4j: ## Neo4j-Tests ausführen (Neo4j muss laufen: bolt://localhost:7687)
	$(PYTEST) tests/ -q -m "neo4j" --tb=short

test-all: ## Alle Tests inkl. Integration und Neo4j ausführen
	$(PYTEST) tests/ -q -m "" --tb=short

clean: ## Cache löschen
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null; true
	find . -type f -name "*.pyc" -delete 2>/dev/null; true
	@echo "✓ Cache bereinigt"

build-extension: ## Bitwig Extensions bauen (benötigt JDK 25)
	cd bitwig-extension && JAVA_HOME=$(JAVA_HOME) ./mvnw package -DskipTests -q
	@mkdir -p $(EXT_DIST)
	@cp bitwig-extension/target/BitwigAgentBridge-fix.jar    $(EXT_DIST)/BitwigAgentBridge.bwextension    2>/dev/null || true
	@cp bitwig-extension/target/BitwigStepPlugin-fix.jar     $(EXT_DIST)/BitwigStepPlugin.bwextension     2>/dev/null || true
	@cp bitwig-extension/target/LaunchpadController-fix.jar  $(EXT_DIST)/LaunchpadController.bwextension  2>/dev/null || true
	@cp bitwig-extension/target/BitwigOscBridge-fix.jar      $(EXT_DIST)/BitwigOscBridge.bwextension      2>/dev/null || true
	@echo "✓ Extensions gebaut → $(EXT_DIST)/"

deploy-local: build-extension ## Extensions lokal auf Linux installieren
	cp $(EXT_DIST)/*.bwextension "$(LOCAL_EXT_DIR)/"
	@echo "✓ Extensions → $(LOCAL_EXT_DIR)/"

deploy-mac: build-extension ## Extensions auf Mac übertragen via SCP (nur StepPlugin + OscBridge)
	scp -o StrictHostKeyChecking=no \
	    -o IdentitiesOnly=yes \
	    -o PreferredAuthentications=publickey,keyboard-interactive,password \
	    $(EXT_DIST)/BitwigStepPlugin.bwextension \
	    $(EXT_DIST)/BitwigOscBridge.bwextension \
	    $(EXT_DIST)/LaunchpadController.bwextension \
	    "$(MAC_USER)@$(MAC_HOST):$(MAC_EXT_DIR)/"
	@# BitwigAgentBridge entfernen (nicht benötigt auf Mac)
	@ssh -o StrictHostKeyChecking=no -o IdentitiesOnly=yes \
	    $(MAC_USER)@$(MAC_HOST) \
	    "rm -f '$(MAC_EXT_DIR)/BitwigAgentBridge.bwextension'" 2>/dev/null || true
	@echo "✓ StepPlugin + OscBridge + LaunchpadAgent → Mac $(MAC_HOST)"

deploy-mac-http: build-extension ## Extensions per HTTP bereitstellen (Mac Browser-Download)
	@fuser -k 8080/tcp 2>/dev/null; sleep 1; true
	@echo ">>> Öffne auf Mac: http://$(LINUX_IP):8080"
	@echo "    Dateien herunterladen → nach $(MAC_EXT_DIR)/ kopieren → Bitwig Extension neu laden"
	$(PYTHON) -m http.server 8080 --directory $(EXT_DIST)

ssh-setup-mac: ## SSH-Key für Mac einrichten (einmalig, dann deploy-mac ohne Passwort)
	@[ -f ~/.ssh/id_rsa.pub ] || ssh-keygen -t rsa -b 4096 -N "" -f ~/.ssh/id_rsa -q
	@echo ">>> Führe auf dem Mac im Terminal aus:"
	@echo ""
	@echo "    mkdir -p ~/.ssh"
	@echo "    echo \"$$(cat ~/.ssh/id_rsa.pub)\" >> ~/.ssh/authorized_keys"
	@echo "    chmod 700 ~/.ssh && chmod 600 ~/.ssh/authorized_keys"
	@echo ""
	@echo "Danach: make deploy-mac"

deploy: deploy-local deploy-mac ## Extensions lokal + Mac installieren


agent-service-install: ## Bitwig Agent als systemd User-Service installieren (autostart)
	@mkdir -p ~/.config/systemd/user
	@install -m 644 scripts/bitwig-agent.service ~/.config/systemd/user/bitwig-agent.service
	@systemctl --user daemon-reload
	@systemctl --user enable bitwig-agent.service
	@echo "✓ bitwig-agent.service installiert und aktiviert (startet beim Login automatisch)"
	@echo "  Starten: make agent-service-start"

agent-service-start: ## Bitwig Agent Service starten
	systemctl --user start bitwig-agent.service
	@sleep 2 && systemctl --user status bitwig-agent.service --no-pager | head -8

agent-service-stop: ## Bitwig Agent Service stoppen
	systemctl --user stop bitwig-agent.service
	@echo "✓ bitwig-agent.service gestoppt"

agent-service-status: ## Bitwig Agent Service Status anzeigen
	systemctl --user status bitwig-agent.service --no-pager

agent-service-logs: ## Bitwig Agent Service Logs live anzeigen (Ctrl+C zum Beenden)
	journalctl --user -u bitwig-agent.service -f

# ── Container (Podman Quadlet) ──────────────────────────────────────────────

container-neo4j-start: ## Neo4j Container starten
	systemctl --user start neo4j.service
	@sleep 3 && systemctl --user status neo4j.service --no-pager | head -6

container-neo4j-stop: ## Neo4j Container stoppen
	systemctl --user stop neo4j.service

container-neo4j-logs: ## Neo4j Logs live anzeigen
	journalctl --user -u neo4j.service -f

container-vllm-build: ## fedora-vllm Image bauen (einmalig, ~24 GB)
	podman build -t localhost/fedora-vllm:latest ~/.local/share/containers/fedora-vllm/
	@echo "✓ Image localhost/fedora-vllm:latest gebaut"

container-vllm-start: ## vLLM Backend (agent/Qwen3-14B-AWQ) starten
	systemctl --user start vllm@agent.service
	@sleep 5 && systemctl --user status vllm@agent.service --no-pager | head -6

container-vllm-stop: ## vLLM Backend stoppen
	systemctl --user stop vllm@agent.service

container-vllm-logs: ## vLLM Logs live anzeigen
	journalctl --user -u vllm@agent.service -f

container-status: ## Status aller Container-Services anzeigen
	@systemctl --user status neo4j.service vllm@agent.service --no-pager 2>/dev/null | grep -E '(●|○|Active|Main PID)'

ollama-setup-mac: ## Ollama auf Mac installieren (manuell auf Mac Terminal ausführen)
	@echo ">>> Führe auf dem Mac Terminal aus:"
	@echo ""
	@echo "  curl -fsSL https://ollama.com/install.sh | sh"
	@echo "  ollama pull qwen3:4b"
	@echo "  launchctl setenv OLLAMA_HOST 0.0.0.0"
	@echo "  # Firewall: TCP 11434 freigeben"
	@echo ""
	@echo "Danach von Linux testen:"
	@echo "  curl http://192.168.0.4:11434/api/tags"

ollama-test: ## Mac LLM-Verbindung testen
	@resp=$$(curl -s --max-time 5 http://$(MAC_HOST):11434/api/tags 2>&1); \
	if [ -z "$$resp" ]; then \
	  echo "✗ Ollama nicht erreichbar (http://$(MAC_HOST):11434)"; \
	  echo "  → Auf Mac: OLLAMA_HOST=0.0.0.0 ollama serve &"; \
	else \
	  echo "$$resp" | python3 -c "import json,sys; m=json.load(sys.stdin); models=m.get('models',[]); [print('  ✓',x['name']) for x in models] if models else print('  Ollama läuft aber keine Modelle — ollama pull qwen3:8b')"; \
	fi

# ── MLX Fine-Tuning (Ansatz 3) ──────────────────────────────────────────────

MLX_MODEL ?= mlx-community/Qwen2.5-3B-Instruct-4bit
MLX_DATA  ?= ./training_data
MLX_OUT   ?= ~/mlx-models

mlx-export: ## MLX Training-Daten aus Neo4j exportieren (→ training_data/)
	$(PYTHON) -c "\
from src.agent.tools.mlx_export import export_training_data; \
import json; \
r = export_training_data('./training_data', min_score=0.70); \
print(json.dumps({k: v for k, v in r.items() if k != 'output_path'}, indent=2, ensure_ascii=False)); \
print('→', r.get('output_path', 'training_data/'))"

mlx-setup: ## MLX + mlx-lm auf Mac installieren (Anleitung)
	@echo ">>> Führe auf dem Mac Terminal aus:"
	@echo ""
	@echo "  # Python-Venv erstellen (Apple Silicon, macOS 14+)"
	@echo "  python3 -m venv ~/.venv-mlx"
	@echo "  source ~/.venv-mlx/bin/activate"
	@echo ""
	@echo "  # MLX-Abhängigkeiten installieren"
	@echo "  pip install mlx mlx-lm huggingface-hub"
	@echo ""
	@echo "  # Basis-Modell herunterladen (4-bit quantized, ~2 GB)"
	@echo "  mkdir -p $(MLX_OUT)"
	@echo "  huggingface-cli download $(MLX_MODEL) --local-dir $(MLX_OUT)/base"
	@echo ""
	@echo "Danach Trainingsdaten übertragen:"
	@echo "  make mlx-sync-data"

mlx-sync-data: ## Trainingsdaten auf Mac übertragen (SCP)
	@[ -f "$(MLX_DATA)/train.jsonl" ] || { echo "✗ Keine Daten — make mlx-export zuerst ausführen"; exit 1; }
	ssh -o StrictHostKeyChecking=no $(MAC_USER)@$(MAC_HOST) "mkdir -p ~/mlx-training"
	scp -o StrictHostKeyChecking=no \
	    $(MLX_DATA)/train.jsonl \
	    $(MLX_DATA)/valid.jsonl \
	    $(MLX_DATA)/export_stats.json \
	    $(MAC_USER)@$(MAC_HOST):~/mlx-training/
	@echo "✓ $(MLX_DATA)/ → Mac:~/mlx-training/ ($(MAC_HOST))"

mlx-train: ## MLX LoRA Fine-Tuning Anleitung anzeigen (auf Mac Terminal ausführen)
	@echo ">>> Führe auf dem Mac Terminal aus:"
	@echo ""
	@echo "  source ~/.venv-mlx/bin/activate"
	@echo ""
	@echo "  # LoRA Fine-Tuning (~30–60 min auf M1/M2, ~15 min auf M3/M4)"
	@echo "  python -m mlx_lm.lora \\"
	@echo "    --model $(MLX_OUT)/base \\"
	@echo "    --train \\"
	@echo "    --data ~/mlx-training \\"
	@echo "    --iters 1000 \\"
	@echo "    --batch-size 4 \\"
	@echo "    --lora-layers 16 \\"
	@echo "    --learning-rate 1e-5 \\"
	@echo "    --save-every 200 \\"
	@echo "    --adapter-path $(MLX_OUT)/bitwig-adapter"
	@echo ""
	@echo "  # Adapter in fertiges Modell einbauen"
	@echo "  python -m mlx_lm.fuse \\"
	@echo "    --model $(MLX_OUT)/base \\"
	@echo "    --adapter-path $(MLX_OUT)/bitwig-adapter \\"
	@echo "    --save-path $(MLX_OUT)/bitwig-finetuned"
	@echo ""
	@echo "Danach als Ollama-Modell bereitstellen:"
	@echo "  make mlx-test"

mlx-test: ## Fine-tuned Modell auf Mac testen (Anleitung)
	@echo ">>> Führe auf dem Mac Terminal aus:"
	@echo ""
	@echo "  source ~/.venv-mlx/bin/activate"
	@echo ""
	@echo "  # Direkter Test mit mlx-lm"
	@echo "  python -m mlx_lm.generate \\"
	@echo "    --model $(MLX_OUT)/bitwig-finetuned \\"
	@echo "    --max-tokens 300 \\"
	@echo "    --prompt 'Erstelle ein 4-taktiges Pattern für Synth Lead in C-Dur, Techno, 128 BPM'"
	@echo ""
	@echo "  # Als Ollama-Modell bereitstellen (optional)"
	@echo "  # → Modelfile erstellen und 'ollama create bitwig-music' ausführen"

ml-export: ## ML Training-Daten aus Neo4j exportieren (für MLX Fine-tuning)
	$(PYTHON) -c "\
from src.knowledge.ml_export import export_patterns_to_jsonl, export_validator_conversations, get_export_stats; \
print(export_patterns_to_jsonl()); \
print(export_validator_conversations()); \
print('Stats:', get_export_stats())"

mlx-setup-mac: ## MLX Fine-tuning Setup auf Mac anzeigen
	@echo "=== MLX Fine-tuning auf Apple Silicon Mac ==="
	@echo ""
	@echo "1. MLX installieren (auf Mac Terminal):"
	@echo "   pip install mlx-lm"
	@echo ""
	@echo "2. Training-Daten von Linux kopieren:"
	@echo "   scp $(LINUX_IP):$(CURDIR)/training_data/*.jsonl ~/training_data/"
	@echo ""
	@echo "3. LoRA Fine-tuning starten (auf Mac Terminal):"
	@echo "   mlx_lm.lora \\"
	@echo "     --model mlx-community/Qwen3-8B-4bit \\"
	@echo "     --train \\"
	@echo "     --data ~/training_data \\"
	@echo "     --iters 100 \\"
	@echo "     --batch-size 4 \\"
	@echo "     --lora-layers 8 \\"
	@echo "     --learning-rate 1e-4"
	@echo ""
	@echo "4. Modell in Ollama registrieren:"
	@echo "   ollama create qwen3-music -f Modelfile"
	@echo ""
	@echo "Voraussetzung: mind. 200 bewertete Patterns (make ml-export zeigt aktuelle Anzahl)"

ml-validate-test: ## Fine-tuned Modell mit Rock-Drums testen
	$(PYTHON) -c "\
from src.agent.tools.music_validator import validate_music_pattern; \
from src.agent.tools.pattern_generators import _drums; \
notes = _drums('rock', 2, 'full'); \
r = validate_music_pattern(notes, 'VD-HEAVY', 'rock', 'A', 'minor'); \
print('Score:', r.get('score')); print('Summary:', r.get('summary')); print('Issues:', r.get('issues'))"

prepare-training-data: ## Datasets herunterladen und in MLX-Format konvertieren
	@echo "=== Training-Daten vorbereiten ==="
	@echo "1. Datasets werden konvertiert..."
	$(PYTHON) -c "\
from src.knowledge.dataset_converter import prepare_all_datasets; \
stats = prepare_all_datasets(); \
print(f'Gesamt: {stats[\"total\"]} Beispiele — Train: {stats[\"train\"]}, Val: {stats[\"val\"]}')"
	@echo ""
	@echo "2. Training-Daten auf Mac kopieren:"
	@echo "   scp training_data/train.jsonl training_data/valid.jsonl $(MAC_USER)@$(MAC_HOST):~/training_data/"
	@echo ""
	@echo "3. MLX Training auf Mac fortsetzen:"
	@echo "   mlx_lm.lora \\"
	@echo "     --model mlx-community/Qwen3-8B-4bit \\"
	@echo "     --adapter-path ~/.ollama/models/mlx-models/bitwig-adapter \\"
	@echo "     --resume-adapter-file ~/.ollama/models/mlx-models/bitwig-adapter/0001000_adapters.safetensors \\"
	@echo "     --data ~/training_data \\"
	@echo "     --iters 500 --batch-size 4 --lora-layers 8"

sync-training-mac: ## Training-Daten auf Mac kopieren
	scp -o StrictHostKeyChecking=no -o IdentitiesOnly=yes \
	    training_data/train.jsonl training_data/valid.jsonl \
	    "$(MAC_USER)@$(MAC_HOST):~/training_data/"
	@echo "✓ Trainingsdaten auf Mac"
