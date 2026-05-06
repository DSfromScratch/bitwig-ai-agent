.DEFAULT_GOAL := help
JAVA_HOME ?= /usr/lib/jvm/java-25-openjdk
VENV     := .venv
PYTHON   := $(shell if [ -x "$(VENV)/bin/python" ]; then printf '%s' "$(VENV)/bin/python"; elif command -v python3 >/dev/null 2>&1; then command -v python3; else command -v python; fi)
STREAMLIT := $(PYTHON) -m streamlit
PYTEST   := $(PYTHON) -m pytest

FILE ?= song.mp3
VLLM_MGR ?= $(shell if [ -x /home/sija/vllm/service-manager.sh ]; then printf '%s' /home/sija/vllm/service-manager.sh; elif [ -x ../vllm/service-manager.sh ]; then printf '%s' ../vllm/service-manager.sh; elif [ -x ./vllm/service-manager.sh ]; then printf '%s' ./vllm/service-manager.sh; fi)

.PHONY: help install download-mf dashboard embed-server agent start analyse validate test clean neo4j neo4j-import vllm-up vllm-down vllm-status stack-up stack-down stack-status build-extension build-plugin install-plugin test-integration test-neo4j test-all

help: ## Verfügbare Befehle anzeigen
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) \
		| awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-14s\033[0m %s\n", $$1, $$2}'

install: ## Abhängigkeiten installieren
	@if [ ! -d "$(VENV)" ]; then uv python install 3.11 && uv venv --python 3.11 $(VENV); fi
	uv pip install --python $(PYTHON) -r requirements.txt

download-mf: ## Music Flamingo Modell herunterladen (~16 GB, einmalig)
	$(PYTHON) -c "\
from huggingface_hub import snapshot_download; \
print('Lade Music Flamingo FP8...'); \
snapshot_download('henry1477/music-flamingo-2601-hf-fp8'); \
print('Download abgeschlossen.')"

neo4j: ## Neo4j Windows Desktop — Starten Sie Neo4j Desktop manuell auf Windows 11
	@echo "💡 Neo4j Desktop auf Windows starten:"
	@echo "   1. Neo4j Desktop öffnen (bereits installiert)"
	@echo "   2. Database starten"
	@echo "   3. bolt://localhost:7687"
	@echo ""
	@echo "Oder SSH-Tunnel von Linux:"
	@echo "   ssh -L 7687:localhost:7687 user@windows-host"

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

vllm-up: ## vLLM Runtime über Service-Manager starten
	@if [ -z "$(VLLM_MGR)" ]; then echo "⚠️  Kein vLLM Service-Manager gefunden"; exit 0; fi
	bash -lc '$(VLLM_MGR) start'

vllm-down: ## vLLM Runtime über Service-Manager stoppen
	@if [ -z "$(VLLM_MGR)" ]; then echo "⚠️  Kein vLLM Service-Manager gefunden"; exit 0; fi
	bash -lc '$(VLLM_MGR) stop'

vllm-status: ## vLLM Runtime Status anzeigen
	@if [ -z "$(VLLM_MGR)" ]; then echo "⚠️  Kein vLLM Service-Manager gefunden"; exit 0; fi
	bash -lc '$(VLLM_MGR) status'

stack-up: ## Vollen Stack starten (vLLM extern, Projektservices)
	$(PYTHON) start_agent.py

stack-down: ## Managed vLLM Runtime stoppen
	@if [ -z "$(VLLM_MGR)" ]; then echo "⚠️  Kein vLLM Service-Manager gefunden"; exit 0; fi
	bash -lc '$(VLLM_MGR) stop'

stack-status: ## Projekt- und Runtime-Status anzeigen
	@if [ -n "$(VLLM_MGR)" ]; then bash -lc '$(VLLM_MGR) status'; else echo "⚠️  Kein vLLM Service-Manager gefunden"; fi
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

build-extension: ## Bitwig Extension JAR bauen (benötigt JDK 25)
	cd bitwig-extension && JAVA_HOME=$(JAVA_HOME) mvn package -q
	@echo "✓ Extension gebaut"

build-plugin: ## Agent UI CLAP-Plugin bauen (benötigt g++ + libX11)
	$(MAKE) -C agent-plugin/src
	@echo "✓ CLAP Plugin gebaut → agent-plugin/build/agent-ui.clap"

install-plugin: build-plugin ## Plugin nach ~/.clap/ installieren (Bitwig neu starten!)
	$(MAKE) -C agent-plugin/src install
