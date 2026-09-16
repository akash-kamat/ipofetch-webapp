# Repository instructions

- Use `uv` exclusively for Python dependency management and execution.
- Do not use `pip`, `poetry`, `pipenv`, or direct `python` commands for project tasks.
- Run Python entry points as `uv run ...` and manage dependencies through `pyproject.toml` / `uv.lock`.
- Preserve the scraper's conservative request pacing; do not increase polling frequency without an explicit reason.

