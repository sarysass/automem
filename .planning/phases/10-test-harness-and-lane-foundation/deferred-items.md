# Deferred Items

- 2026-04-17: `uv run pytest -m "not slow"` still fails in `tests/test_repository_layout.py::test_repository_has_no_legacy_product_names_or_private_paths` because `.claude/settings.local.json` and existing phase planning docs contain `/Users/shali` strings. This predates `10-02` and is out of scope for HARN-02 runtime-entrypoint coverage.
