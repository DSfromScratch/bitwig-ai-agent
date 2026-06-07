.PHONY: agent agent-service-install agent-service-logs agent-service-start agent-service-status agent-service-stop analyse analyze-grid analyze-grid-local build-extension clean container-neo4j-logs container-neo4j-start container-neo4j-stop container-status container-vllm-build container-vllm-logs container-vllm-start container-vllm-stop dashboard deploy deploy-local deploy-mac deploy-mac-http download-mf embed-server help ingest-arranger ingest-audio ingest-audio-dry ingest-midi ingest-project ingest-project-dry install ml-export ml-validate-test mlx-export mlx-ingest-scales mlx-rl-eval mlx-rl-pairs mlx-rl-train mlx-setup mlx-sync-data mlx-test mlx-train neo4j-import ollama-setup-mac ollama-test scan-vsts screenshot-server show-grids ssh-setup-mac stack-down stack-status stack-up start test test-all test-integration test-neo4j validate yt-ingest yt-ingest-dry

.DEFAULT_GOAL := help

# ── Toolchain ────────────────────────────────────────────────────────────────
VENV      := .venv
PYTHON    := $(shell if [ -e "$(VENV)/bin/python" ] && "$(VENV)/bin/python" --version >/dev/null 2>&1; then printf '%s' "$(VENV)/bin/python"; elif command -v python3.11 >/dev/null 2>&1; then command -v python3.11; elif command -v python3 >/dev/null 2>&1; then command -v python3; else command -v python; fi)
UV        := $(shell command -v uv 2>/dev/null || echo $$HOME/.local/bin/uv)
STREAMLIT := $(PYTHON) -m streamlit
PYTEST    := $(PYTHON) -m pytest

# JDK 25 (nur für build-extension nötig; lazy ausgewertet). Sucht Homebrew,
# macOS java_home, SDKMAN und Standard-Linux-Pfade.
JAVA_HOME ?= $(or \
  $(wildcard /opt/homebrew/opt/openjdk@25),\
  $(wildcard /opt/homebrew/opt/openjdk),\
  $(shell /usr/libexec/java_home -v 25 2>/dev/null),\
  $(firstword $(wildcard $(HOME)/.sdkman/candidates/java/*25*)),\
  $(wildcard /usr/lib/jvm/java-25-openjdk),\
  $(error JDK 25 nicht gefunden — JAVA_HOME explizit setzen))

# ── Pfade & Remote ───────────────────────────────────────────────────────────
FILE          ?= song.mp3
MAC_HOST      ?= 192.168.0.4
MAC_USER      ?= sija
MAC_EXT_DIR   := /Users/$(MAC_USER)/Documents/Bitwig Studio/Extensions
LOCAL_EXT_DIR := $(HOME)/Bitwig Studio/Extensions
LINUX_IP      := $(shell ip route get 1 2>/dev/null | awk '{print $$7; exit}')
EXT_DIST      := bitwig-extension/dist

# MLX Fine-Tuning
MLX_MODEL ?= mlx-community/Qwen2.5-3B-Instruct-4bit
MLX_DATA  ?= ./training_data
MLX_OUT   ?= ~/mlx-models

# ── Hilfe ────────────────────────────────────────────────────────────────────
help: ## Diese Hilfe anzeigen
	@awk 'BEGIN {FS = ":.*##"} \
	  /^##@/ {printf "\n\033[1m%s\033[0m\n", substr($$0,5); next} \
	  /^[a-zA-Z0-9_-]+:.*##/ {printf "  \033[36m%-22s\033[0m %s\n", $$1, $$2}' \
	  $(MAKEFILE_LIST)

##@ Setup

install: ## Abhängigkeiten installieren (uv venv + requirements)
	@if [ ! -d "$(VENV)" ]; then $(UV) python install 3.11 && $(UV) venv --python 3.11 $(VENV); fi
	$(UV) pip install --python $(PYTHON) -r requirements.txt

download-mf: ## Music Flamingo Modell herunterladen (~16 GB, einmalig)
	$(PYTHON) -c "\
	from huggingface_hub import snapshot_download; \
	print('Lade Music Flamingo FP8...'); \
	snapshot_download('henry1477/music-flamingo-2601-hf-fp8'); \
	print('Download abgeschlossen.')"

clean: ## Python-Cache löschen
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null; true
	find . -type f -name "*.pyc" -delete 2>/dev/null; true
	@echo "✓ Cache bereinigt"

##@ Stack & Services

start: ## 🚀 MCP Server + Agent starten (vollständiger Stack)
	$(PYTHON) start_agent.py

agent: ## Interaktiven CLI-Agent starten (vLLM nötig)
	@LD_LIBRARY_PATH=.cuda_compat:$(LD_LIBRARY_PATH) $(PYTHON) -m src.agent.core

embed-server: ## Lokalen Embedding-Server starten (Port 8080)
	$(PYTHON) start_agent.py --embed-server-up

dashboard: ## Streamlit Dashboard starten (Port 8501)
	$(STREAMLIT) run dashboard/app.py --server.port 8501

stack-up: ## Vollen Stack starten (Neo4j + vLLM + Agent)
	systemctl --user start neo4j.service vllm@agent.service
	$(PYTHON) start_agent.py

stack-down: ## Stack stoppen (Neo4j + vLLM)
	systemctl --user stop vllm@agent.service neo4j.service

stack-status: ## Stack-Status anzeigen
	@systemctl --user status neo4j.service vllm@agent.service --no-pager 2>/dev/null | grep -E '(●|○|Active|Main PID)'
	$(PYTHON) start_agent.py --status-only

agent-service-install: ## Agent als systemd User-Service installieren (autostart)
	@mkdir -p ~/.config/systemd/user
	@install -m 644 scripts/bitwig-agent.service ~/.config/systemd/user/bitwig-agent.service
	@systemctl --user daemon-reload
	@systemctl --user enable bitwig-agent.service
	@echo "✓ bitwig-agent.service installiert und aktiviert (Autostart beim Login)"
	@echo "  Starten: make agent-service-start"

agent-service-start: ## Agent Service starten
	systemctl --user start bitwig-agent.service
	@sleep 2 && systemctl --user status bitwig-agent.service --no-pager | head -8

agent-service-stop: ## Agent Service stoppen
	systemctl --user stop bitwig-agent.service
	@echo "✓ bitwig-agent.service gestoppt"

agent-service-status: ## Agent Service Status anzeigen
	systemctl --user status bitwig-agent.service --no-pager

agent-service-logs: ## Agent Service Logs live anzeigen (Ctrl+C beendet)
	journalctl --user -u bitwig-agent.service -f

##@ Container (Podman Quadlet)

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

container-vllm-start: ## vLLM Backend (Qwen3-14B-AWQ) starten
	systemctl --user start vllm@agent.service
	@sleep 5 && systemctl --user status vllm@agent.service --no-pager | head -6

container-vllm-stop: ## vLLM Backend stoppen
	systemctl --user stop vllm@agent.service

container-vllm-logs: ## vLLM Logs live anzeigen
	journalctl --user -u vllm@agent.service -f

container-status: ## Status aller Container-Services anzeigen
	@systemctl --user status neo4j.service vllm@agent.service --no-pager 2>/dev/null | grep -E '(●|○|Active|Main PID)'

##@ Knowledge-Base & Ingest

neo4j-import: ## Neo4j Graph aus Bitwig-Installation neu aufbauen
	$(PYTHON) -c "\
	from src.knowledge.neo4j_graph import create_schema, build_graph; \
	create_schema(); build_graph(); print('✓ Neo4j Graph aufgebaut')"

scan-vsts: ## Installierte VST-Plugins scannen und in Neo4j speichern
	$(PYTHON) -c "from src.knowledge.vst_scanner import scan_and_store; print(scan_and_store())"

ingest-midi: ## MIDI-Clips lesen + Tonart/Akkorde/Rhythmus analysieren
	$(PYTHON) scripts/ingest_midi_clips.py --project "$(PROJECT)" $(ARGS)

ingest-audio: ## WAV-Samples eines Projekts analysieren + in Neo4j
	$(PYTHON) scripts/ingest_audio_samples.py --project "$(PROJECT)" $(ARGS)

ingest-audio-dry: ## Dry-Run: zeigt was ingest-audio analysieren würde
	$(PYTHON) scripts/ingest_audio_samples.py --project "$(PROJECT)" --dry-run

ingest-project: ## Aktuelles Bitwig-Projekt live scannen + Sound-Rezepte
	$(PYTHON) scripts/ingest_live_project.py --project "$(PROJECT)" $(ARGS)

ingest-project-dry: ## Dry-Run: zeigt was ingest-project tun würde
	$(PYTHON) scripts/ingest_live_project.py --project "$(PROJECT)" --dry-run

ingest-arranger: ## Arranger-Tracks interaktiv ingesten (Track anklicken → Enter)
	$(PYTHON) scripts/ingest_arranger_tracks.py --project "$(PROJECT)" $(ARGS)

yt-ingest: ## Bitwig YouTube-Transkripte holen und in Neo4j speichern
	$(PYTHON) scripts/ingest_youtube_transcripts.py --channel "@bitwig" $(ARGS)

yt-ingest-dry: ## Dry-Run: zeigt was yt-ingest tun würde (kein Embed-Server)
	$(PYTHON) scripts/ingest_youtube_transcripts.py --channel "@bitwig" --limit 10 --dry-run

##@ Analyse & Vision

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

analyze-grid-local: ## Grid lokal analysieren: Surya OCR + OpenCV + NetworkX (kein API-Key)
	$(PYTHON) scripts/analyze_grid_local.py --project "$(PROJECT)" $(ARGS)

analyze-grid: ## Grid-Screenshot mit Claude Vision analysieren → Neo4j
	$(PYTHON) scripts/analyze_grid_screenshot.py --project "$(PROJECT)" $(ARGS)

show-grids: ## Grid-Patches als Mermaid-Workflow + VNC-Screenshots anzeigen
	$(PYTHON) scripts/show_grid_workflow.py --project "$(PROJECT)" $(ARGS)

screenshot-server: ## Screenshot-Server-Anleitung (auf dem Mac ausführen)
	@echo ">>> Auf dem Mac in einem Terminal ausführen:"
	@echo "    python3 agent-plugin/screenshot_server.py"

##@ Tests

test: ## Unit-Tests ausführen
	$(PYTEST) tests/ -q

test-integration: ## Integration-Tests (Mock-OSC, kein Bitwig nötig)
	BITWIG_TEST_MODE=mock $(PYTEST) tests/ -q -m "integration" --tb=short

test-neo4j: ## Neo4j-Tests (Neo4j muss laufen: bolt://localhost:7687)
	$(PYTEST) tests/ -q -m "neo4j" --tb=short

test-all: ## Alle Tests inkl. Integration und Neo4j
	$(PYTEST) tests/ -q -m "" --tb=short

##@ Bitwig Extension

build-extension: ## Bitwig Extensions bauen (benötigt JDK 25)
	@[ -x "$(JAVA_HOME)/bin/javac" ] || { echo "✗ JDK 25 nicht unter JAVA_HOME=$(JAVA_HOME) — JAVA_HOME setzen"; exit 1; }
	cd bitwig-extension && JAVA_HOME=$(JAVA_HOME) ./mvnw package -DskipTests -q
	@# Die .bwextension-Dateien werden vom pom (antrun) direkt nach $(EXT_DIST) geschrieben.
	@set -e; for f in BitwigAgentBridge BitwigStepPlugin LaunchpadController BitwigOscBridge; do \
	    [ -s "$(EXT_DIST)/$$f.bwextension" ] || { echo "✗ Artefakt fehlt: $(EXT_DIST)/$$f.bwextension"; exit 1; }; \
	  done
	@echo "✓ Extensions gebaut → $(EXT_DIST)/  (Bitwig vor Deploy beenden, vermeidet '?'-Icon)"

deploy-local: build-extension ## Extensions lokal installieren (Linux)
	cp $(EXT_DIST)/*.bwextension '$(LOCAL_EXT_DIR)/'
	@echo "✓ Extensions → $(LOCAL_EXT_DIR)/"

deploy-mac: build-extension ## Extensions auf Mac übertragen via SCP
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
	@echo "    Dateien herunterladen → nach $(MAC_EXT_DIR)/ kopieren → Bitwig neu laden"
	$(PYTHON) -m http.server 8080 --directory $(EXT_DIST)

deploy: deploy-local deploy-mac ## Extensions lokal + Mac installieren


ssh-setup-mac: ## SSH-Key für Mac einrichten (einmalig)
	@[ -f ~/.ssh/id_rsa.pub ] || ssh-keygen -t rsa -b 4096 -N "" -f ~/.ssh/id_rsa -q
	@echo ">>> Führe auf dem Mac im Terminal aus:"
	@echo ""
	@echo "    mkdir -p ~/.ssh"
	@echo "    echo \"$$(cat ~/.ssh/id_rsa.pub)\" >> ~/.ssh/authorized_keys"
	@echo "    chmod 700 ~/.ssh && chmod 600 ~/.ssh/authorized_keys"
	@echo ""
	@echo "Danach: make deploy-mac"

##@ Training (MLX / RL)

mlx-export: ## Trainingsdaten aus Neo4j exportieren (min_score, → training_data/)
	$(PYTHON) -c "\
	from src.agent.tools.mlx_export import export_training_data; \
	import json; \
	r = export_training_data('./training_data', min_score=0.70); \
	print(json.dumps({k: v for k, v in r.items() if k != 'output_path'}, indent=2, ensure_ascii=False)); \
	print('→', r.get('output_path', 'training_data/'))"

ml-export: ## ML Training-Daten exportieren (Patterns + Validator-Conversations)
	$(PYTHON) -c "\
	from src.knowledge.ml_export import export_patterns_to_jsonl, export_validator_conversations, get_export_stats; \
	print(export_patterns_to_jsonl()); \
	print(export_validator_conversations()); \
	print('Stats:', get_export_stats())"

mlx-sync-data: ## Trainingsdaten auf Mac übertragen (→ ~/mlx-training/)
	@[ -f "$(MLX_DATA)/train.jsonl" ] || { echo "✗ Keine Daten — make mlx-export zuerst"; exit 1; }
	ssh -o StrictHostKeyChecking=no $(MAC_USER)@$(MAC_HOST) "mkdir -p ~/mlx-training"
	scp -o StrictHostKeyChecking=no \
	    $(MLX_DATA)/train.jsonl \
	    $(MLX_DATA)/valid.jsonl \
	    $(MLX_DATA)/export_stats.json \
	    $(MAC_USER)@$(MAC_HOST):~/mlx-training/
	@echo "✓ $(MLX_DATA)/ → Mac:~/mlx-training/ ($(MAC_HOST))"

mlx-setup: ## MLX + mlx-lm auf Mac installieren (Anleitung)
	@echo ">>> Führe auf dem Mac Terminal aus:"
	@echo ""
	@echo "  python3 -m venv ~/.venv-mlx"
	@echo "  source ~/.venv-mlx/bin/activate"
	@echo "  pip install mlx mlx-lm huggingface-hub"
	@echo "  mkdir -p $(MLX_OUT)"
	@echo "  huggingface-cli download $(MLX_MODEL) --local-dir $(MLX_OUT)/base"
	@echo ""
	@echo "Danach Trainingsdaten übertragen: make mlx-sync-data"

mlx-train: ## MLX LoRA Fine-Tuning Anleitung (auf Mac ausführen)
	@echo ">>> Führe auf dem Mac Terminal aus:"
	@echo ""
	@echo "  source ~/.venv-mlx/bin/activate"
	@echo "  python -m mlx_lm lora \\"
	@echo "    --model $(MLX_OUT)/base --train --data ~/mlx-training \\"
	@echo "    --iters 1000 --batch-size 1 --num-layers 16 \\"
	@echo "    --learning-rate 1e-5 --save-every 200 --grad-checkpoint \\"
	@echo "    --max-seq-length 512 --adapter-path $(MLX_OUT)/bitwig-adapter"
	@echo ""
	@echo "  python -m mlx_lm.fuse --model $(MLX_OUT)/base \\"
	@echo "    --adapter-path $(MLX_OUT)/bitwig-adapter \\"
	@echo "    --save-path $(MLX_OUT)/bitwig-finetuned"

mlx-test: ## Fine-tuned Modell auf Mac testen (Anleitung)
	@echo ">>> Führe auf dem Mac Terminal aus:"
	@echo ""
	@echo "  source ~/.venv-mlx/bin/activate"
	@echo "  python -m mlx_lm.generate --model $(MLX_OUT)/bitwig-finetuned \\"
	@echo "    --max-tokens 300 \\"
	@echo "    --prompt 'Erstelle ein 4-taktiges Pattern für Synth Lead in C-Dur, Techno, 128 BPM'"

mlx-ingest-scales: ## Alle 24 Tonarten + Akkorde in Neo4j ingesten
	source .venv/bin/activate && python scripts/ingest_scales.py

mlx-rl-pairs: ## DPO-Paare generieren (Fine-tuned Modell, Port 8080)
	source .venv/bin/activate && python scripts/generate_dpo_pairs.py \
			--model-url http://$(MAC_HOST):8080/v1/chat/completions \
			--data-dir ./training_data \
			--max-prompts 60

mlx-rl-eval: ## Reward-Score des Fine-tuned Modells messen (Port 8080)
	source .venv/bin/activate && python3 -c "\
	from scripts.rl_train_loop import evaluate; \
	score = evaluate('http://$(MAC_HOST):8080/v1/chat/completions'); \
	print(f'avg_reward = {score:.3f}')"

mlx-rl-train: ## RL-Trainingsschleife starten (generieren → SFT → evaluieren)
	source .venv/bin/activate && python scripts/rl_train_loop.py \
			--reward-threshold 0.90 \
			--rounds 10

ml-validate-test: ## Fine-tuned Modell mit Rock-Drums testen
	$(PYTHON) -c "\
	from src.agent.tools.music_validator import validate_music_pattern; \
	from src.agent.tools.pattern_generators import _drums; \
	notes = _drums('rock', 2, 'full'); \
	r = validate_music_pattern(notes, 'VD-HEAVY', 'rock', 'A', 'minor'); \
	print('Score:', r.get('score')); print('Summary:', r.get('summary')); print('Issues:', r.get('issues'))"

##@ Remote / Mac LLM

ollama-setup-mac: ## Ollama auf Mac installieren (Anleitung)
	@echo ">>> Führe auf dem Mac Terminal aus:"
	@echo ""
	@echo "  curl -fsSL https://ollama.com/install.sh | sh"
	@echo "  ollama pull qwen3:4b"
	@echo "  launchctl setenv OLLAMA_HOST 0.0.0.0"
	@echo "  # Firewall: TCP 11434 freigeben"
	@echo ""
	@echo "Danach von Linux testen:  curl http://$(MAC_HOST):11434/api/tags"

ollama-test: ## Mac LLM-Verbindung testen
	@resp=$$(curl -s --max-time 5 http://$(MAC_HOST):11434/api/tags 2>&1); \
	if [ -z "$$resp" ]; then \
	  echo "✗ Ollama nicht erreichbar (http://$(MAC_HOST):11434)"; \
	  echo "  → Auf Mac: OLLAMA_HOST=0.0.0.0 ollama serve &"; \
	else \
	  echo "$$resp" | python3 -c "import json,sys; m=json.load(sys.stdin); models=m.get('models',[]); [print('  ✓',x['name']) for x in models] if models else print('  Ollama läuft aber keine Modelle — ollama pull qwen3:8b')"; \
	fi

