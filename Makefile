BIN := $(if $(wildcard .venv/bin),.venv/bin/,)

.PHONY: install test lint pipeline app readme figures

install:
	$(BIN)pip install -e ".[dev]"

test:
	$(BIN)pytest -q

lint:
	$(BIN)ruff check .

pipeline:
	$(BIN)python -m wealthadvisor.pipeline ingest

app:
	$(BIN)streamlit run app/Home.py

readme:
	$(BIN)python -m scripts.readme_results

figures:
	$(BIN)python -m scripts.readme_figures
