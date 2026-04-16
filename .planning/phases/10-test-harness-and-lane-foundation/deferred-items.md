# Deferred Items

- 2026-04-17: `uv run pytest -m "not slow"` still fails in `tests/test_repository_layout.py::test_repository_has_no_legacy_product_names_or_private_paths` because `.claude/settings.local.json` and existing phase planning docs contain absolute local home-directory paths. This predates `10-02` and is out of scope for HARN-02 runtime-entrypoint coverage.
- 2026-04-17: Adversarial review finding #9 (slow-lane `uv run` cold-start cost) is deferred to Phase 13 / QUAL-01 canary-and-quality-gates policy. Why: this is lane-governance and developer-experience work, not a correctness gap in the Phase 10 harness. Owner: revisit during Phase 13 planning.
- 2026-04-17: Adversarial review finding #10 (FakeMemory ↔ real mem0 contract-parity test lane) is deferred to v2 `ADV-01`. Why: it needs a real-dependency contract lane, which v1.1 explicitly keeps out of scope. Owner: revisit when the v2 advanced-testing milestone starts.
