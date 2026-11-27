"""r12 worker memory: the Celery task module stays light (heavy libraries load in the task child), gc.freeze in the
parent, and the stale-task sweeper's liveness check and settings guard."""
import gc
import os
import subprocess
import sys
from pathlib import Path

import pytest

HEAVY = ("app.platform.engines", "app.services.gee.firris_pipeline", "ee", "pyogrio", "sklearn", "matplotlib",
         "rasterio", "geopandas", "scipy")
APP_ROOT = Path(__file__).resolve().parents[2]


def test_the_task_module_does_not_load_the_engines_or_heavy_libraries():
    code = ("import sys, app.workers.celery_tasks, app.core.celery_app\n"
            f"print(','.join(m for m in {HEAVY!r} if m in sys.modules))")
    done = subprocess.run([sys.executable, "-c", code], cwd=APP_ROOT, capture_output=True, text=True, timeout=300,
                          env={**os.environ, "APP_ENV": "test"})
    assert done.returncode == 0, done.stderr[-2000:]
    assert done.stdout.strip().splitlines()[-1:] in ([], [""]), f"heavy modules loaded by the parent: {done.stdout}"


def test_the_engine_still_loads_inside_the_task():
    from app.platform.engines import get_engine_adapter
    assert get_engine_adapter("firris") is not None


def test_worker_init_freezes_the_parent_heap():
    from app.workers.celery_tasks import freeze_parent_heap
    gc.unfreeze()
    try:
        freeze_parent_heap()
        assert gc.get_freeze_count() > 0
    finally:
        gc.unfreeze()


def test_live_task_ids_reads_the_task_argument_and_is_unknown_when_the_broker_fails(monkeypatch):
    from app.core.celery_app import celery_app
    from app.services.tasks import stale_sweeper

    class Inspect:
        def __init__(self, reply): self.reply = reply
        def active(self):
            if isinstance(self.reply, Exception):
                raise self.reply
            return self.reply

    monkeypatch.setattr(stale_sweeper, "_live_cache", None)
    monkeypatch.setattr(celery_app.control, "inspect",
                        lambda timeout: Inspect({"w1": [{"args": ["abc"]}, {"args": []}], "w2": []}))
    assert stale_sweeper.live_task_ids() == frozenset({"abc"})
    monkeypatch.setattr(stale_sweeper, "_live_cache", None)
    monkeypatch.setattr(celery_app.control, "inspect", lambda timeout: Inspect(None))  # no worker replied
    assert stale_sweeper.live_task_ids() == frozenset()
    monkeypatch.setattr(stale_sweeper, "_live_cache", None)
    monkeypatch.setattr(celery_app.control, "inspect", lambda timeout: Inspect(ConnectionError("broker down")))
    assert stale_sweeper.live_task_ids() is None


def test_the_stale_limit_cannot_be_shorter_than_the_hard_time_limit():
    from app.core.config import Settings
    with pytest.raises(ValueError, match="stale-task limit"):
        Settings(app_env="test", celery_task_soft_time_limit_seconds=100, celery_task_time_limit_seconds=200,
                 firris_stale_running_seconds=199)
