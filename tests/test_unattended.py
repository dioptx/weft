"""F2: unattended mode — on_fail=block parks the workflow in 'waiting' (instead of
failing/hanging), /resume continues it, and both survive rebuild."""

import os
import sys
from pathlib import Path

import pytest

PLUGIN_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PLUGIN_ROOT))

from core import state_machine, event_store  # noqa: E402

TEMPLATE = {
    "name": "unattended-test",
    "steps": [
        {"name": "build", "on_fail": "block"},
        {"name": "gate", "on_fail": "block"},
    ],
}


@pytest.fixture
def unattended_env():
    old = os.environ.get("WEFT_UNATTENDED")
    os.environ["WEFT_UNATTENDED"] = "1"
    yield
    if old is None:
        os.environ.pop("WEFT_UNATTENDED", None)
    else:
        os.environ["WEFT_UNATTENDED"] = old


def test_unattended_block_parks_to_waiting(project_dir, unattended_env):
    state = state_machine.start_workflow(TEMPLATE, "s1", str(project_dir))
    state = state_machine.step_fail(state, "needs human", "s1", str(project_dir))
    assert state["status"] == "waiting"
    # step is parked, not failed — work isn't abandoned
    assert state["steps"][0]["status"] == "running"
    types = [e["event_type"] for e in event_store.query(str(project_dir))]
    assert "wf.needs_human" in types
    assert "wf.failed" not in types


def test_attended_block_still_fails(project_dir):
    os.environ.pop("WEFT_UNATTENDED", None)
    state = state_machine.start_workflow(TEMPLATE, "s1", str(project_dir))
    state = state_machine.step_fail(state, "boom", "s1", str(project_dir))
    assert state["status"] == "failed"
    assert state["steps"][0]["status"] == "failed"


def test_resume_waiting_to_running(project_dir, unattended_env):
    state = state_machine.start_workflow(TEMPLATE, "s1", str(project_dir))
    state = state_machine.step_fail(state, "park", "s1", str(project_dir))
    assert state["status"] == "waiting"
    state = state_machine.resume(state, "fixed it", "s1", str(project_dir))
    assert state["status"] == "running"
    types = [e["event_type"] for e in event_store.query(str(project_dir))]
    assert "wf.resumed" in types
    # can advance normally after resume
    state = state_machine.step_complete(state, "", "s1", str(project_dir))
    assert state["steps"][0]["status"] == "complete"


def test_resume_rejects_non_waiting(project_dir):
    state = state_machine.start_workflow(TEMPLATE, "s1", str(project_dir))
    with pytest.raises(ValueError):
        state_machine.resume(state, "", "s1", str(project_dir))


def test_waiting_survives_rebuild(project_dir, unattended_env):
    state = state_machine.start_workflow(TEMPLATE, "s1", str(project_dir))
    state_machine.step_fail(state, "park", "s1", str(project_dir))
    rebuilt = state_machine.rebuild_from_events(project_dir=str(project_dir))
    assert rebuilt["status"] == "waiting"


def test_resumed_state_survives_rebuild(project_dir, unattended_env):
    state = state_machine.start_workflow(TEMPLATE, "s1", str(project_dir))
    state = state_machine.step_fail(state, "park", "s1", str(project_dir))
    state_machine.resume(state, "back", "s1", str(project_dir))
    rebuilt = state_machine.rebuild_from_events(project_dir=str(project_dir))
    assert rebuilt["status"] == "running"


NOTIFY_TEMPLATE = {
    "name": "notify-test",
    "notify": True,
    "steps": [
        {"name": "build"},
        {"name": "gate", "on_fail": "block", "notify": True},
    ],
}


def test_notify_flag_threads_through_start(project_dir):
    """The opt-in notify flag (Track 2 notify-at-gate) is stored verbatim on the
    workflow and per-step — weft only records it; the gate watcher acts on it."""
    state = state_machine.start_workflow(NOTIFY_TEMPLATE, "s1", str(project_dir))
    assert state["notify"] is True
    assert state["steps"][1]["notify"] is True
    # default when absent
    assert state["steps"][0]["notify"] is None


def test_notify_flag_defaults_false(project_dir):
    state = state_machine.start_workflow(TEMPLATE, "s1", str(project_dir))
    assert state["notify"] is False


def test_notify_flag_survives_rebuild(project_dir):
    state_machine.start_workflow(NOTIFY_TEMPLATE, "s1", str(project_dir))
    rebuilt = state_machine.rebuild_from_events(project_dir=str(project_dir))
    assert rebuilt["notify"] is True
    assert rebuilt["steps"][1]["notify"] is True
