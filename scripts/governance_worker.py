#!/usr/bin/env python3
from __future__ import annotations

import errno
import json
import logging
import os
import socket
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Any

import httpx
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


def build_base_url() -> str:
    configured = os.environ.get("MEMORY_URL")
    if configured:
        return configured.rstrip("/")
    host = os.environ.get("BIND_HOST", "127.0.0.1")
    port = os.environ.get("BIND_PORT", "8888")
    return f"http://{host}:{port}"


def build_client() -> httpx.Client:
    api_key = os.environ.get("MEMORY_API_KEY") or os.environ.get("ADMIN_API_KEY", "")
    if not api_key:
        raise RuntimeError("Missing MEMORY_API_KEY or ADMIN_API_KEY")
    request_timeout = max(30.0, float(os.environ.get("AUTOMEM_WORKER_REQUEST_TIMEOUT_SECONDS", "900")))
    return httpx.Client(
        base_url=build_base_url(),
        headers={"X-API-Key": api_key},
        timeout=httpx.Timeout(connect=10.0, write=30.0, pool=30.0, read=request_timeout),
        trust_env=False,
    )


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
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)


def run_once(client: Any, *, worker_id: str) -> dict[str, Any]:
    response = client.post(
        "/governance/jobs/run-next",
        json={
            "worker_id": worker_id,
            "lease_seconds": max(30, int(os.environ.get("AUTOMEM_WORKER_LEASE_SECONDS", "300"))),
        },
    )
    if response.status_code != 200:
        raise RuntimeError(f"governance worker failed with status {response.status_code}: {getattr(response, 'text', '')}")
    return response.json()


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
        "Starting governance worker with once=%s poll_seconds=%s base_url=%s worker_id=%s",
        once,
        poll_seconds,
        build_base_url(),
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
        with build_client() as client:
            while True:
                try:
                    result = run_once(client, worker_id=worker_id)
                except httpx.HTTPError as exc:
                    logger.error("Worker request failed: %s", exc)
                    return 1
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
