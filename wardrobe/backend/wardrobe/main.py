"""FastAPI 应用工厂。"""

import logging
from pathlib import Path

from fastapi import APIRouter, FastAPI
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from starlette.exceptions import HTTPException as StarletteHTTPException

from . import __version__
from .api import (
    data,
    dictionaries,
    images,
    imports,
    items,
    outfits,
    products,
    proposals,
    purchases,
    similar,
    suggestions,
    system,
    tag_suggestions,
)
from .config import Settings, load_settings
from .db import current_revision, head_revision, make_engine, make_sessionmaker, run_migrations
from .errors import install_error_handlers
from .security import LocalOnlyMiddleware
from .seed import seed_defaults
from .storage.backup import check_no_interrupted_restore, create_backup
from .storage.images import gc_orphans

log = logging.getLogger("wardrobe")
# 网页界面自身的 HTML 使用严格的 CSP（Swagger 文档页从 CDN 加载资源，因此不套用）
UI_CSP = (
    "default-src 'self'; img-src 'self' data: blob:; style-src 'self' 'unsafe-inline'; script-src 'self'; "
    "connect-src 'self'; font-src 'self'; frame-ancestors 'none'; base-uri 'self'; form-action 'self'"
)


def install_spa(app: FastAPI, dist: Path) -> None:
    """托管 Vite 构建产物。前端路由（如 /items/12）都回退到 index.html；/api、/media 不回退。"""
    root = dist.resolve()

    @app.get("/{path:path}", include_in_schema=False)
    def spa(path: str):
        if path == "api" or path.startswith(("api/", "media/")):
            raise StarletteHTTPException(404, "Not Found")
        target = (root / path).resolve()
        if path and target.is_file() and root in target.parents:
            headers = {"Cache-Control": "public, max-age=31536000, immutable"} if path.startswith("assets/") else {}
            if target.suffix.lower() == ".html":
                headers = {"Content-Security-Policy": UI_CSP, "Cache-Control": "no-cache"}
            return FileResponse(target, headers=headers)
        # 缺失的静态文件和数据库/备份等文件路径不属于前端路由。
        if path.startswith("assets/") or Path(path).suffix:
            raise StarletteHTTPException(404, "Not Found")
        return FileResponse(
            root / "index.html", headers={"Content-Security-Policy": UI_CSP, "Cache-Control": "no-cache"}
        )


API_DESCRIPTION = """
本机衣橱管理 API。

* 所有写请求必须带 `X-Wardrobe-Client` 头（`web-ui` / `cli` / `ai:<name>`）。
* 修改核心实体（product / purchase / purchase_line / wardrobe_item / outfit）必须带当前 `version`
  （body 或 `If-Match`），冲突返回 409 `VERSION_CONFLICT`。
* 非 `web-ui` / `cli` 请求方修改已核实记录的受保护字段时，返回 202 并生成待确认提议；
  删除等不允许的操作仍返回 409 `VERIFIED_PROTECTED`。
* `GET /api/v1/meta` 返回所有枚举值。
"""


def prepare_database(settings: Settings):
    """建目录 → 检查未完成的恢复 → （有待执行迁移且已有数据时先备份）→ 迁移 → 初始数据 → 清理孤儿图片。"""
    settings.ensure_dirs()
    check_no_interrupted_restore(settings)
    existed = settings.db_path.exists()
    engine = make_engine(settings.db_path)
    if existed and current_revision(engine) != head_revision():
        backup = create_backup(settings, "pre-migrate")
        log.info("迁移前已备份到 %s", backup.name)
    run_migrations(engine)
    factory = make_sessionmaker(engine)
    with factory() as session:
        seed_defaults(session)
    gc_orphans(settings, factory)
    return engine, factory


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or load_settings()
    engine, factory = prepare_database(settings)

    app = FastAPI(
        title="Wardrobe API",
        version=__version__,
        description=API_DESCRIPTION,
        docs_url="/api/docs",
        redoc_url=None,
        openapi_url="/api/openapi.json",
    )
    app.state.settings = settings
    app.state.engine = engine
    app.state.sessionmaker = factory
    app.add_middleware(LocalOnlyMiddleware, settings=settings)
    install_error_handlers(app)

    v1 = APIRouter(prefix="/api/v1")
    for module in (
        system,
        dictionaries,
        products,
        purchases,
        items,
        similar,
        suggestions,
        tag_suggestions,
        outfits,
        images,
        proposals,
        imports,
        data,
    ):
        v1.include_router(module.router)
    app.include_router(v1)

    app.mount("/media", StaticFiles(directory=settings.images_dir), name="media")
    dist = settings.frontend_dist
    if (dist / "index.html").is_file():
        install_spa(app, dist)
    else:

        @app.get("/", include_in_schema=False)
        def index():
            return HTMLResponse(
                "<!doctype html><meta charset='utf-8'><title>Wardrobe</title>"
                "<body style='font-family:system-ui;max-width:40rem;margin:4rem auto;line-height:1.7'>"
                "<h1>Wardrobe</h1><p>后端已运行。网页界面将在 Phase 3 提供。</p>"
                "<p><a href='/api/docs'>打开 API 文档（Swagger）</a></p></body>"
            )

    return app
