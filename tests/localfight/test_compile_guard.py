"""Tests for the first-compile serialisation in runner.py (no generator)."""

import threading
import time

from src.localfight import runner


def _reset():
    with runner._warm_lock:
        runner._warmed.clear()
        runner._path_locks.clear()


def test_scenario_ai_paths_reads_both_keys():
    d = {"entities": [[{"ai": "a/main"}, {"ai_path": "b/main"}], [{"ai": "a/main"}, {}]]}
    assert runner._scenario_ai_paths(d) == ["a/main", "b/main", "a/main"]


def test_first_fight_per_path_is_exclusive_then_free():
    _reset()
    active, peak, lock = [0], [0], threading.Lock()

    def fight():
        with runner._compile_guard(["x/main"], nocache=False):
            with lock:
                active[0] += 1
                peak[0] = max(peak[0], active[0])
            time.sleep(0.02)
            with lock:
                active[0] -= 1

    threads = [threading.Thread(target=fight) for _ in range(6)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    # The very first fight ran alone; once warmed, the guard no longer holds anything.
    assert "x/main" in runner._warmed
    with runner._compile_guard(["x/main"], nocache=False):
        assert not runner._path_locks["x/main"].locked()


def test_failed_first_fight_does_not_mark_warm():
    _reset()
    try:
        with runner._compile_guard(["y/main"], nocache=False):
            raise RuntimeError("boom")
    except RuntimeError:
        pass
    assert "y/main" not in runner._warmed
    assert not runner._path_locks["y/main"].locked()


def test_nocache_bypasses_the_guard():
    _reset()
    with runner._compile_guard(["z/main"], nocache=True):
        assert "z/main" not in runner._path_locks
    assert "z/main" not in runner._warmed
