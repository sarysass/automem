#!/usr/bin/env python3
from __future__ import annotations

import errno
import json
import logging
import os
import socket
import sys
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Callable

from dotenv import load_dotenv


logger = logging.getLogger("automem.governance_worker")


def load_runtime_env() -> None:
    explicit = os.environ.get("AUTOMEM_ENV_FILE")
    candidates: list[Path] = []
    if explicit:
        candidates.append(Path(explicit))
    script_dir = Path(__file__).resolve().parent
    repo_root = script_dir.parent
    candidates.extend(
        [
            repo_root / ".env",
            repo_root / "backend" / ".env",
        ]
    )
    for candidate in candidates:
        if candidate.exists():
            load_dotenv(candidate)


def _import_backend_dispatch() -> tuple[Callable[..., Any], Callable[..., Any], Callable[[], None]]:
    """Lazy import of backend.main internals so this script can run without
    starting the FastAPI server. backend.main reads ZAI_API_KEY and friends
    at module init time, so callers MUST run load_runtime_env() first.
    """
    repo_root = Path(__file__).resolve().parents[1]
    if str(repo_root) not in sys.path:
        sys.path.insert(0, str(repo_root))
    from backend.main import (
        claim_next_governance_job,
        dispatch_governance_job,
        ensure_task_db,
    )
    return claim_next_governance_job, dispatch_governance_job, ensure_task_db


def build_lock_path() -> Path:
    configured = os.environ.get("AUTOMEM_WORKER_LOCK_FILE")
    if configured:
        return Path(configured)
    return Path(os.environ.get("TASK_DB_PATH", Path(__file__).resolve().parents[1] / "data" / "tasks" / "tasks.db")).with_suffix(
        ".worker.lock"
    )


def _read_lock_pid(lock_path: Path) -> int | None:
    try:
        raw = lock_path.read_text(encoding="utf-8").strip()
    except FileNotFoundError:
        return None
    if not raw:
        return None
    try:
        pid = int(raw)
    except ValueError:
        return None
    return pid if pid > 0 else None


def _pid_is_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


@contextmanager
def single_worker_lock(lock_path: Path):
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    fd: int | None = None
    acquired = False
    try:
        while True:
            try:
                fd = os.open(lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
                os.write(fd, str(os.getpid()).encode("utf-8"))
                acquired = True
                break
            except OSError as exc:
                if exc.errno != errno.EEXIST:
                    raise
                existing_pid = _read_lock_pid(lock_path)
                if existing_pid is not None and _pid_is_alive(existing_pid):
                    yield False
                    return
                try:
                    lock_path.unlink()
                except FileNotFoundError:
                    continue
        yield True
    finally:
        if fd is not None:
            os.close(fd)
        if acquired:
            try:
                lock_path.unlink()
            except FileNotFoundError:
                pass


def build_worker_id() -> str:
    configured = os.environ.get("AUTOMEM_WORKER_ID")
    if configured:
        return configured.strip()
    return f"automem-worker@{socket.gethostname()}"


def configure_logging() -> None:
    level_name = (os.environ.get("AUTOMEM_WORKER_LOG_LEVEL") or "INFO").strip().upper()
    level = getattr(logging, level_name, logging.INFO)
    logging.basicConfig(
        level=level,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )


def run_once(*, worker_id: str, lease_seconds: int | None = None) -> dict[str, Any]:
    """Claim the next governance job and dispatch it in-process.

    Returns the same shape the /v1/governance/jobs/run-next endpoint returns:
    {"status": "idle" | "processed", "worker_id": ..., "job": optional}.
    """
    claim, dispatch, ensure_db = _import_backend_dispatch()
    ensure_db()
    if lease_seconds is None:
        lease_seconds = max(30, int(os.environ.get("AUTOMEM_WORKER_LEASE_SECONDS", "300")))
    claimed = claim(worker_id=worker_id, job_types=None, lease_seconds=lease_seconds)
    if not claimed:
        return {"status": "idle", "worker_id": worker_id}
    job = dispatch(claimed, worker_id=worker_id)
    return {"status": "processed", "worker_id": worker_id, "job": job}


def summarize_result(result: dict[str, Any]) -> str:
    status = str(result.get("status") or "unknown")
    if status == "processed":
        job = result.get("job") or {}
        summary = (
            f"status=processed job_id={job.get('job_id')} job_type={job.get('job_type')} "
            f"job_status={job.get('status')} attempt={job.get('attempts')} "
            f"worker_id={result.get('worker_id')}"
        )
        error_text = str(job.get("error_text") or "").strip()
        if error_text:
            summary += f' error="{error_text}"'
        return summary
    return f"status={status} worker_id={result.get('worker_id')}"


def main() -> int:
    load_runtime_env()
    configure_logging()
    poll_seconds = max(1.0, float(os.environ.get("AUTOMEM_WORKER_POLL_SECONDS", "5")))
    once = (os.environ.get("AUTOMEM_WORKER_ONCE") or "true").strip().lower() in {"1", "true", "yes", "on"}
    worker_id = build_worker_id()
    logger.info(
        "Starting governance worker with once=%s poll_seconds=%s worker_id=%s",
        once,
        poll_seconds,
        worker_id,
    )
    idle_streak = 0
    with single_worker_lock(build_lock_path()) as acquired:
        if not acquired:
            logger.warning("Worker lock exists; skipping startup")
            # Sentinel-wrapped so runtime_drivers can parse payload even on skipped path.
            # Source of truth for sentinel strings: tests/support/runtime_drivers.py
            print("===AUTOMEM_PAYLOAD_BEGIN===")
            print(json.dumps({"status": "skipped", "reason": "lock_exists"}, ensure_ascii=False))
            print("===AUTOMEM_PAYLOAD_END===")
            return 0
        while True:
            try:
                result = run_once(worker_id=worker_id)
            except Exception as exc:
                logger.error("Worker loop failed: %s", exc)
                return 1
            status = str(result.get("status") or "unknown")
            if status == "processed":
                idle_streak = 0
                logger.info("Worker processed governance job: %s", summarize_result(result))
            elif status == "idle":
                idle_streak += 1
                if once or idle_streak == 1 or idle_streak % 12 == 0:
                    logger.info(
                        "Worker idle; no governance job claimed (idle_streak=%s worker_id=%s)",
                        idle_streak,
                        worker_id,
                    )
            else:
                idle_streak = 0
                logger.info("Worker poll result: %s", summarize_result(result))
            if once:
                # Sentinel-wrapped final payload so runtime_drivers._parse_payload
                # can locate it regardless of any log noise.
                # Source of truth for sentinel strings: tests/support/runtime_drivers.py
                print("===AUTOMEM_PAYLOAD_BEGIN===")
                print(json.dumps(result, ensure_ascii=False))
                print("===AUTOMEM_PAYLOAD_END===")
                logger.info("Governance worker exiting with final status=%s", result.get("status"))
                break
            logger.debug("Sleeping for %s seconds before the next poll", poll_seconds)
            time.sleep(poll_seconds)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
