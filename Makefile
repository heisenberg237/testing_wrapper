PYTHON ?= python3
PIP ?= pip3

.PHONY: install install-dev test lint format check list-configs run-batch-example clean

install:
	$(PIP) install -e .

install-dev:
	$(PIP) install -e ".[dev]"

test:
	$(PYTHON) -m pytest -q

lint:
	$(PYTHON) -m flake8 src tests usage_examples.py

format:
	$(PYTHON) -m black src tests usage_examples.py

check: lint test

list-configs:
	$(PYTHON) -m mle_heatmap_wrapper.cli.main --list-configs

run-batch-example:
	$(PYTHON) -m mle_heatmap_wrapper.cli.main --input-dir data/in/mlx --part-number 362 --supplier MLX --output output --metrics widthness tangent

clean:
	$(PYTHON) -c "import pathlib, shutil; [shutil.rmtree(p) for p in pathlib.Path('.').rglob('__pycache__') if p.is_dir()]"
	rm -rf .pytest_cache .mypy_cache .coverage .coverage.* htmlcov
