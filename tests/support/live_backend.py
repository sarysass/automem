from __future__ import annotations

import argparse
import importlib.util
import os
import socket
import subprocess
import sys
import uuid
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator

import pytest
import uvicorn

from tests.support.fake_memory import FakeMemory
from tests.support.waiting import wait_for_http_ready


@dataclass(frozen=True)
class LiveBackendHarness:
    base_url: str
    temp_dir: Path
    task_db_path: Path
    history_db_path: Path
    worker_lock_path: Path
    consolidate_lock_path: Path
    repo_task_db_path: Path
    admin_api_key: str

    @property
    def auth_headers(self) -> dict[str, str]:
        return {"X-API-Key": self.admin_api_key}

    def url(self, path: str) -> str:
        normalized = path if path.startswith("/") else f"/{path}"
        return f"{self.base_url}{normalized}"


def repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def build_temp_env(temp_dir: Path, *, host: str, port: int) -> dict[str, str]:
    task_db_path = temp_dir / "tasks.db"
    history_db_path = temp_dir / "history.db"
    env = os.environ.copy()
    env.update(
        {
            "ADMIN_API_KEY": "test-admin",
            "TASK_DB_PATH": str(task_db_path),
            "HISTORY_DB_PATH": str(history_db_path),
            "ZAI_API_KEY": "test-zai-key",
            "ZAI_BASE_URL": "https://example.invalid",
            "ZAI_MODEL": "glm-test",
            "OLLAMA_BASE_URL": "http://127.0.0.1:11434",
            "OLLAMA_EMBED_MODEL": "nomic-embed-text",
            "QDRANT_HOST": "127.0.0.1",
            "QDRANT_PORT": "6333",
            "QDRANT_COLLECTION": "test-automem",
            "AUTOMEM_WORKER_LOCK_FILE": str(temp_dir / "tasks.worker.lock"),
            "MEMORY_CONSOLIDATE_LOCK_FILE": str(temp_dir / "tasks.consolidate.lock"),
            "BIND_HOST": host,
            "BIND_PORT": str(port),
            "MEMORY_URL": f"http://{host}:{port}",
        }
    )
    return env


def reserve_tcp_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        sock.listen(1)
        return int(sock.getsockname()[1])


def load_backend_module():
    module_path = repo_root() / "backend" / "main.py"
    spec = importlib.util.spec_from_file_location(f"automem_live_backend_{uuid.uuid4().hex}", module_path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Unable to load backend module from {module_path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    module.MEMORY_BACKEND = FakeMemory()
    module.ensure_task_db()
    return spec.name, module


def serve_backend(*, host: str, port: int) -> None:
    module_name = ""
    try:
        module_name, module = load_backend_module()
        config = uvicorn.Config(
            module.app,
            host=host,
            port=port,
            log_level="warning",
            access_log=False,
        )
        server = uvicorn.Server(config)
        server.run()
    finally:
        if module_name:
            sys.modules.pop(module_name, None)


@contextmanager
def running_live_backend(temp_dir: Path) -> Iterator[LiveBackendHarness]:
    host = "127.0.0.1"
    port = reserve_tcp_port()
    env = build_temp_env(temp_dir, host=host, port=port)
    log_path = temp_dir / "live-backend.log"
    temp_dir.mkdir(parents=True, exist_ok=True)

    with log_path.open("w", encoding="utf-8") as log_file:
        process = subprocess.Popen(
            [
                sys.executable,
                "-m",
                "tests.support.live_backend",
                "--host",
                host,
                "--port",
                str(port),
            ],
            cwd=repo_root(),
            env=env,
            stdout=log_file,
            stderr=subprocess.STDOUT,
            text=True,
        )

    harness = LiveBackendHarness(
        base_url=f"http://{host}:{port}",
        temp_dir=temp_dir,
        task_db_path=temp_dir / "tasks.db",
        history_db_path=temp_dir / "history.db",
        worker_lock_path=temp_dir / "tasks.worker.lock",
        consolidate_lock_path=temp_dir / "tasks.consolidate.lock",
        repo_task_db_path=repo_root() / "data" / "tasks" / "tasks.db",
        admin_api_key=env["ADMIN_API_KEY"],
    )

    try:
        try:
            wait_for_http_ready(harness.base_url)
        except TimeoutError as exc:
            process.poll()
            log_output = log_path.read_text(encoding="utf-8") if log_path.exists() else ""
            raise RuntimeError(
                f"Live backend failed to become ready (exit={process.returncode}). Log output:\n{log_output}"
            ) from exc
        yield harness
    finally:
        process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=5)


@pytest.fixture()
def live_backend(tmp_path: Path) -> Iterator[LiveBackendHarness]:
    with running_live_backend(tmp_path) as harness:
        yield harness


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", required=True, type=int)
    args = parser.parse_args(argv)
    serve_backend(host=args.host, port=args.port)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
