BIN := $(if $(wildcard .venv/bin),.venv/bin/,)

.PHONY: install test lint pipeline app

install:
	$(BIN)pip install -e ".[dev]"

test:
	$(BIN)pytest -q

lint:
	$(BIN)ruff check .

pipeline:
	$(BIN)python -m wealthadvisor.pipeline

app:
	$(BIN)streamlit run app/streamlit_app.py
