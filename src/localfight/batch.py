"""
Persistent generator workers: one JVM each, many fights.

A one-shot JVM spends most of a fight JIT-compiling the AI, and N of them in
parallel starve each other (6 workers: 2.9s -> 13.3s per fight). A worker
that stays up keeps the compiled AI cached and the JIT'd code hot.

Protocol (java/BatchMain.java): the worker prints `READY`, then one JSON
line per scenario path written to its stdin -- the stock entry point's
document, or `{"error": "..."}`. Generator chatter goes to stderr, captured
in `.cache/batch/worker-<n>.log`.

    with GeneratorPool(workers=8) as pool:
        results = pool.map([s.to_json() for s in scenarios])

Flags and measurements: src/localfight/README.md.
"""

from __future__ import annotations

import json
import os
import queue
import select
import subprocess
import tempfile
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Callable, Iterable, Optional

from src.common.config import get_paths

from .runner import RunnerError, _compile_guard, _scenario_ai_paths, get_generator_path, get_java_path

JAVA_SRC = Path(__file__).parent / "java" / "BatchMain.java"

# Each worker is a single fight thread. Left to its defaults a JVM sizes its
# GC and JIT thread pools for the whole machine, and N of them starve each
# other; SerialGC and a 2-CPU view keep each worker to roughly two cores.
# The heap cap matters with 8 workers: the default max is 1/4 of RAM each.
#
# C1 only (TieredStopAtLevel=1) is deliberate and measured, not a guess:
# 8 hot workers on Claudius/Claudias, 48 fights -- C1 4.1s per fight,
# 1.87 fights/s; full tiered C2 10.1s per fight, 0.76 fights/s. The AI's
# generated class is huge and C2 never pays for itself on it, even warm.
DEFAULT_JVM_FLAGS = (
    "-XX:+UseSerialGC", "-XX:ActiveProcessorCount=2", "-XX:TieredStopAtLevel=1", "-Xmx3g",
)


def _batch_dir() -> Path:
    return get_paths().root / ".cache" / "batch"


def ensure_batch_main() -> Path:
    """Compile BatchMain against generator.jar if the class is missing or stale. Returns the class dir."""
    out = _batch_dir()
    out.mkdir(parents=True, exist_ok=True)
    cls = out / "BatchMain.class"
    jar = get_generator_path()
    if cls.exists() and cls.stat().st_mtime >= max(JAVA_SRC.stat().st_mtime, jar.stat().st_mtime):
        return out
    javac = get_java_path().parent / "javac"
    if not javac.exists():
        raise RunnerError(f"No javac next to {get_java_path()}; the generator toolchain JDK is needed to build BatchMain")
    proc = subprocess.run(
        [str(javac), "-d", str(out), "-cp", str(jar), str(JAVA_SRC)],
        capture_output=True, text=True, timeout=300,
    )
    if proc.returncode != 0:
        raise RunnerError(f"javac failed for {JAVA_SRC}:\n{proc.stderr}")
    return out


class GeneratorWorker:
    """One persistent generator JVM."""

    def __init__(self, index: int, jvm_flags: Iterable[str] = DEFAULT_JVM_FLAGS, nocache: bool = False):
        classes = ensure_batch_main()
        self.index = index
        self.log_path = _batch_dir() / f"worker-{index}.log"
        self._log = open(self.log_path, "wb")
        cmd = [str(get_java_path()), *jvm_flags, "-cp", f"{get_generator_path()}{os.pathsep}{classes}", "BatchMain"]
        if nocache:
            cmd.append("--nocache")
        self.proc = subprocess.Popen(
            cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=self._log,
            cwd=get_paths().generator_dir, bufsize=0,
        )
        self._buf = b""
        self.fights = 0
        ready = self._readline(timeout=120.0)
        if ready != "READY":
            self.close()
            raise RunnerError(f"generator worker {index} did not start (got {ready!r}); see {self.log_path}")

    @property
    def alive(self) -> bool:
        return self.proc.poll() is None

    def _readline(self, timeout: float) -> str:
        """Read one line from the worker, killing it on timeout or EOF."""
        fd = self.proc.stdout.fileno()
        deadline = time.monotonic() + timeout
        while b"\n" not in self._buf:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                self.close()
                raise RunnerError(f"generator worker {self.index} timed out after {timeout:.0f}s; see {self.log_path}")
            ready, _, _ = select.select([fd], [], [], min(remaining, 1.0))
            if not ready:
                continue
            chunk = os.read(fd, 1 << 16)
            if not chunk:
                self.close()
                raise RunnerError(f"generator worker {self.index} exited (code {self.proc.returncode}); see {self.log_path}")
            self._buf += chunk
        line, _, self._buf = self._buf.partition(b"\n")
        return line.decode("utf-8", errors="replace").rstrip("\r")

    def run(self, scenario_json: str, timeout: float = 600.0) -> dict:
        """Play one scenario and return the generator's JSON document."""
        if not self.alive:
            raise RunnerError(f"generator worker {self.index} is dead; see {self.log_path}")
        try:
            ai_paths = _scenario_ai_paths(json.loads(scenario_json))
        except ValueError as e:
            raise RunnerError(f"scenario is not JSON: {e}")
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            f.write(scenario_json)
            path = Path(f.name)
        try:
            with _compile_guard(ai_paths, nocache=False):
                self.proc.stdin.write((str(path) + "\n").encode())
                self.proc.stdin.flush()
                line = self._readline(timeout)
        finally:
            path.unlink(missing_ok=True)
        try:
            result = json.loads(line)
        except json.JSONDecodeError as e:
            raise RunnerError(f"generator worker {self.index} returned non-JSON: {e}\n{line[:500]}")
        if isinstance(result, dict) and "error" in result and len(result) == 1:
            raise RunnerError(f"generator error:\n{result['error']}")
        self.fights += 1
        return result

    def close(self) -> None:
        if self.proc.poll() is None:
            try:
                self.proc.stdin.close()
            except OSError:
                pass
            try:
                self.proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.proc.kill()
                self.proc.wait()
        try:
            self.proc.stdout.close()
        except OSError:
            pass
        self._log.close()


class GeneratorPool:
    """N persistent workers, handed scenarios as they go idle."""

    def __init__(
        self,
        workers: Optional[int] = None,
        jvm_flags: Iterable[str] = DEFAULT_JVM_FLAGS,
        nocache: bool = False,
        timeout: float = 600.0,
    ):
        # Physical cores, not hyperthreads: a fight thread plus its JIT/GC
        # helpers already fill one.
        self.workers = workers or max(1, (os.cpu_count() or 4) // 2)
        self.jvm_flags = tuple(jvm_flags)
        self.nocache = nocache
        self.timeout = timeout
        self._idle: "queue.Queue[GeneratorWorker]" = queue.Queue()
        self._all: list[GeneratorWorker] = []
        self._spawn_lock = threading.Lock()
        self._next_index = 0
        self._closed = False

    def _spawn(self) -> GeneratorWorker:
        with self._spawn_lock:
            index = self._next_index
            self._next_index += 1
        worker = GeneratorWorker(index, self.jvm_flags, self.nocache)
        with self._spawn_lock:
            self._all.append(worker)
        return worker

    def _acquire(self) -> GeneratorWorker:
        with self._spawn_lock:
            can_spawn = len(self._all) < self.workers
        if can_spawn:
            try:
                return self._idle.get_nowait()
            except queue.Empty:
                return self._spawn()
        return self._idle.get()

    def run(self, scenario_json: str) -> dict:
        """Play one scenario on whichever worker is free (blocks until one is)."""
        if self._closed:
            raise RunnerError("GeneratorPool is closed")
        worker = self._acquire()
        try:
            return worker.run(scenario_json, timeout=self.timeout)
        finally:
            if worker.alive:
                self._idle.put(worker)
            else:
                # A dead worker is replaced lazily by the next _acquire().
                with self._spawn_lock:
                    self._all.remove(worker)

    def map(
        self,
        scenario_jsons: Iterable[str],
        progress: Optional[Callable[[int, int], None]] = None,
    ) -> list[Optional[dict]]:
        """Play every scenario; a failed one yields None (its error is re-raised only if all fail)."""
        items = list(scenario_jsons)
        out: list[Optional[dict]] = [None] * len(items)
        errors: list[tuple[int, RunnerError]] = []
        done = 0
        lock = threading.Lock()

        def one(i: int) -> None:
            nonlocal done
            try:
                out[i] = self.run(items[i])
            except RunnerError as e:
                errors.append((i, e))
            with lock:
                done += 1
                if progress:
                    progress(done, len(items))

        with ThreadPoolExecutor(max_workers=self.workers) as ex:
            list(ex.map(one, range(len(items))))
        if items and len(errors) == len(items):
            raise errors[0][1]
        return out

    def close(self) -> None:
        self._closed = True
        for w in list(self._all):
            w.close()
        self._all.clear()

    def __enter__(self) -> "GeneratorPool":
        return self

    def __exit__(self, *exc) -> None:
        self.close()
