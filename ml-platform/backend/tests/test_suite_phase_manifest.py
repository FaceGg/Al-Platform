"""Phase-based suite registry tests (AutoML Agent plan, Task A1.1).

The backend acceptance runner gains a ``--phase pN`` flag alongside the
historical ``--week N`` flag so the AutoML Agent milestones (P1-P6) register
their test modules without occupying week keys. Week keys stay untouched:
``18`` remains reserved for the deferred Week 18 track.
"""

import subprocess
import sys
from pathlib import Path

from tests.week_manifest import (
    ALL_TEST_MODULES,
    PHASE_TEST_MODULES,
    WEEK_TEST_MODULES,
)

BACKEND_DIR = Path(__file__).resolve().parents[1]
RUN_SUITE = BACKEND_DIR / "run_suite.py"


def _run_suite(*argv: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(RUN_SUITE), *argv],
        capture_output=True,
        text=True,
        cwd=BACKEND_DIR,
    )


def test_phase_registry_has_six_phase_keys():
    assert set(PHASE_TEST_MODULES) == {"p1", "p2", "p3", "p4", "p5", "p6"}
    assert all(isinstance(modules, list) for modules in PHASE_TEST_MODULES.values())


def test_phase_p1_self_registered_and_merged():
    assert "test_suite_phase_manifest" in PHASE_TEST_MODULES["p1"]
    assert "test_suite_phase_manifest" in ALL_TEST_MODULES


def test_phase_modules_do_not_collide_with_week_modules():
    week_modules = {
        module
        for modules in WEEK_TEST_MODULES.values()
        for module in modules
    }
    phase_modules = {
        module
        for modules in PHASE_TEST_MODULES.values()
        for module in modules
    }
    assert not week_modules & phase_modules
    assert len(ALL_TEST_MODULES) == len(set(ALL_TEST_MODULES))


def test_run_suite_phase_empty_group_passes():
    empty_phases = [
        phase
        for phase, modules in sorted(PHASE_TEST_MODULES.items())
        if not modules
    ]
    assert empty_phases, "at least one phase should still be an unstarted group"
    phase = empty_phases[0]
    result = _run_suite("--phase", phase)
    assert result.returncode == 0, result.stdout + result.stderr
    assert f"Running phase {phase} acceptance suite (0 modules)." in result.stdout
    assert "0 passed, 0 failed out of 0 modules" in result.stdout


def test_run_suite_phase_flag_validates_choices():
    result = _run_suite("--phase", "p99")
    assert result.returncode != 0
    assert "invalid choice" in result.stderr


def test_run_suite_week_flag_still_validates_choices():
    result = _run_suite("--week", "999")
    assert result.returncode != 0
    assert "invalid choice" in result.stderr


def test_run_suite_rejects_week_and_phase_together():
    result = _run_suite("--week", "16", "--phase", "p1")
    assert result.returncode != 0
    assert "not allowed with argument" in result.stderr
