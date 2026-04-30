"""Health, UI, metrics, runtime-topology HTTP handlers.

Module-isolation contract (tests/conftest.py):
The test suite re-imports backend/main.py via importlib.spec_from_file_location
under a synthetic module name `automem_backend_<tmp>`. That fixture instance
is NOT the canonical `backend.main`. CONFIG / TASK_DB_PATH / FRONTEND_BUILD_DIR
live as module attributes that tests mutate per-fixture (see
test_ui_route_reports_missing_build_artifacts which sets
backend_module.FRONTEND_BUILD_DIR). Routers therefore must NOT bind to
canonical `backend.main` — instead, main.py at import time assigns
`health._main_module = sys.modules[__name__]`, and handlers read those
attributes via that pointer. Whichever main.py loads last (the active one)
wins, which is correct since tests run sequentially and use only their
fixture's app.
"""

from __future__ import annotations

from typing import Any, Optional

from fastapi import APIRouter, Depends
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse, Response

from backend.auth import require_scope, verify_api_key
from backend.metrics import build_runtime_topology, compute_metrics

router = APIRouter()

# Set by main.py at import time so handlers can read CONFIG / TASK_DB_PATH /
# FRONTEND_BUILD_DIR from the active main module (canonical in production,
# per-fixture loaded module in tests). See module docstring.
_main_module: Optional[Any] = None


def _main():
    if _main_module is not None:
        return _main_module
    # Production fallback when main.py forgot to wire us up.
    from backend import main as _m  # noqa: PLC0415
    return _m


@router.get("/")
def root():
    return RedirectResponse(url="/docs")


@router.get("/favicon.ico")
def favicon():
    return Response(status_code=204)


@router.get("/v1/ui")
def ui_index():
    index_path = _main().FRONTEND_BUILD_DIR / "index.html"
    if not index_path.exists():
        return HTMLResponse(
            """
            <!doctype html>
            <html lang="zh-CN">
              <head>
                <meta charset="UTF-8" />
                <meta name="viewport" content="width=device-width, initial-scale=1.0" />
                <title>UI build missing</title>
                <style>
                  body { font-family: "Songti SC", "STSong", serif; background:#f5f2eb; color:#201c16; padding:48px; }
                  .panel { max-width:760px; margin:0 auto; background:#fbf8f2; border:1px solid #ddd4c7; border-radius:24px; padding:28px 32px; }
                  h1 { margin:0 0 12px; font-size:32px; }
                  p { margin:8px 0; line-height:1.7; }
                  code { background:#efe8dc; padding:2px 8px; border-radius:999px; }
                </style>
              </head>
              <body>
                <div class="panel">
                  <h1>前端构建产物不存在</h1>
                  <p>当前仓库还没有生成可供后端直接托管的 UI 产物。</p>
                  <p>请先在 <code>frontend/</code> 下执行 <code>npm install</code> 和 <code>npm run build</code>，再重新访问 <code>/ui</code>。</p>
                </div>
              </body>
            </html>
            """,
            status_code=503,
        )
    return FileResponse(index_path)


@router.get("/v1/healthz")
def healthz(auth: dict[str, Any] = Depends(verify_api_key)):
    require_scope(auth, "search")
    main = _main()
    return {
        "ok": True,
        "llm_model": main.CONFIG["llm"]["config"]["model"],
        "embed_model": main.CONFIG["embedder"]["config"]["model"],
        "qdrant": f"{main.CONFIG['vector_store']['config']['host']}:{main.CONFIG['vector_store']['config']['port']}",
        "task_db": str(main.TASK_DB_PATH),
        "runtime": build_runtime_topology(),
        "metrics": compute_metrics(),
    }


@router.get("/v1/runtime-topology")
def runtime_topology(auth: dict[str, Any] = Depends(verify_api_key)):
    require_scope(auth, "metrics")
    return {"runtime": build_runtime_topology(), "metrics": compute_metrics()["governance_jobs"]}


@router.get("/v1/metrics")
def metrics(auth: dict[str, Any] = Depends(verify_api_key)):
    require_scope(auth, "metrics")
    return {"metrics": compute_metrics()}
