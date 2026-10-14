SHELL := /bin/zsh
VENV := .venv
PY := $(VENV)/bin/python
NODE_BIN := $(HOME)/.nvm/versions/node/v24.20.0/bin
export PATH := $(NODE_BIN):$(PATH)

.PHONY: venv install dev-backend dev-frontend build test

venv:
	python3 -m venv $(VENV)

install: venv
	$(PY) -m pip install -U pip
	$(PY) -m pip install -r requirements.txt -r requirements-dev.txt
	cd frontend && npm install

dev-backend:
	$(VENV)/bin/uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload

dev-frontend:
	cd frontend && npm run dev

build:
	cd frontend && npm run build

test:
	$(PY) -m pytest -q
