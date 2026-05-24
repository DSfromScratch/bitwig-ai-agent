.DEFAULT_GOAL := help
JAVA_HOME ?= $(or $(wildcard $(HOME)/.sdkman/candidates/java/25.0.2-open),$(wildcard /usr/lib/jvm/java-25-openjdk),$(error JDK 25 nicht gefunden — JAVA_HOME setzen))
VENV     := .venv
PYTHON   := $(shell if [ -e "$(VENV)/bin/python" ] && "$(VENV)/bin/python" --version >/dev/null 2>&1; then printf '%s' "$(VENV)/bin/python"; elif command -v python3.11 >/dev/null 2>&1; then command -v python3.11; elif command -v python3 >/dev/null 2>&1; then command -v python3; else command -v python; fi)
UV       := $(shell command -v uv 2>/dev/null || echo $$HOME/.local/bin/uv)
STREAMLIT := $(PYTHON) -m streamlit
PYTEST   := $(PYTHON) -m pytest

FILE ?= song.mp3

.PHONY: help install download-mf dashboard embed-server agent start analyse validate test clean neo4j-import build-extension test-integration test-neo4j test-all agent-service-install agent-service-start agent-service-stop agent-service-status agent-service-logs container-neo4j-start container-neo4j-stop container-neo4j-logs container-vllm-start container-vllm-stop container-vllm-logs container-vllm-build container-status

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

neo4j-import: ## Neo4j Graph aus Bitwig-Installation neu aufbauen
	$(PYTHON) -c "\
from src.knowledge.neo4j_graph import create_schema, build_graph; \
create_schema(); build_graph(); print('✓ Neo4j Graph aufgebaut')"

dashboard: ## Streamlit Dashboard starten
	$(STREAMLIT) run dashboard/app.py --server.port 8501

embed-server: ## Lokalen Embedding-Server starten (Port 8080, kein HF-Netzwerk)
	$(PYTHON) start_agent.py --embed-server-up

agent: ## Interaktiven CLI-Agent starten (vLLM nötig)
	LD_LIBRARY_PATH=.cuda_compat:$(LD_LIBRARY_PATH) $(PYTHON) -m src.agent.core

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

build-extension: ## Bitwig Extension JAR bauen (benötigt JDK 25; Maven wird automatisch heruntergeladen)
	cd bitwig-extension && JAVA_HOME=$(JAVA_HOME) ./mvnw package -DskipTests -q
	@echo "✓ Extension gebaut → bitwig-extension/dist/BitwigAgentBridge.bwextension"
	@echo "  Manuell nach Windows kopieren: cp bitwig-extension/dist/*.bwextension /mnt/c/Users/<User>/Documents/Bitwig\\ Studio/Extensions/"


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
