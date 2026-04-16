from __future__ import annotations

from pathlib import Path
import tomllib


REPO_ROOT = Path(__file__).resolve().parents[1]
PYPROJECT_PATH = REPO_ROOT / "pyproject.toml"
VALIDATION_PATH = (
    REPO_ROOT / ".planning/phases/10-test-harness-and-lane-foundation/10-VALIDATION.md"
)
PHASE_10_LIVE_SLOW_SUITES = (
    REPO_ROOT / "tests/test_harness_foundation_live.py",
    REPO_ROOT / "tests/test_runtime_entrypoints_live.py",
)
FAST_LANE_COMMAND = 'uv run pytest -m "not slow"'
SLOW_LANE_COMMAND = (
    "uv run pytest -m slow "
    "tests/test_harness_foundation_live.py tests/test_runtime_entrypoints_live.py"
)


def load_pyproject() -> dict[str, object]:
    with PYPROJECT_PATH.open("rb") as handle:
        return tomllib.load(handle)


def test_pyproject_registers_strict_lane_markers_and_subprocess_coverage() -> None:
    pyproject = load_pyproject()
    pytest_options = pyproject["tool"]["pytest"]["ini_options"]
    addopts = pytest_options["addopts"]

    assert "-q" in addopts.split()
    assert "--strict-markers" in addopts.split()

    markers = pytest_options["markers"]
    assert any(marker.startswith("slow:") for marker in markers)
    assert any(marker.startswith("serial:") for marker in markers)

    coverage_run = pyproject["tool"]["coverage"]["run"]
    assert coverage_run["parallel"] is True
    assert "subprocess" in coverage_run["patch"]


def test_phase_10_live_suites_are_marked_slow_and_serial() -> None:
    for suite_path in PHASE_10_LIVE_SLOW_SUITES:
        text = suite_path.read_text(encoding="utf-8")
        assert "pytest.mark.slow" in text, suite_path.name
        assert "pytest.mark.serial" in text, suite_path.name
        assert "pytest.mark.timeout(" in text, suite_path.name


def test_phase_10_validation_documents_fast_and_slow_lane_commands() -> None:
    validation = VALIDATION_PATH.read_text(encoding="utf-8")
    assert FAST_LANE_COMMAND in validation
    assert SLOW_LANE_COMMAND in validation
