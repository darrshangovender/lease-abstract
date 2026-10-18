.PHONY: install test lint bench clean

install:
	pip install -e ".[dev]"

test:
	pytest tests/ -q

lint:
	ruff check .

bench:
	python eval/run.py

clean:
	rm -rf .pytest_cache .ruff_cache *.egg-info
	find . -name __pycache__ -type d -prune -exec rm -rf {} +
