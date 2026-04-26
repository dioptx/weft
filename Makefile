.PHONY: help install test lint clean

help:
	@echo "weft — make targets"
	@echo ""
	@echo "  make install    Editable install with dev extras"
	@echo "  make test       Run pytest"
	@echo "  make lint       Run pyright (if available)"
	@echo "  make clean      Remove build artefacts and caches"

install:
	pip install -e ".[dev]"

test:
	pytest -q

lint:
	@command -v pyright >/dev/null 2>&1 && pyright || echo "pyright not installed, skipping"

clean:
	rm -rf build/ dist/ *.egg-info .pytest_cache
	find . -type d -name __pycache__ -exec rm -rf {} +
	find . -type f -name "*.pyc" -delete
