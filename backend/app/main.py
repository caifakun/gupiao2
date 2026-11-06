import logging
import time
from pathlib import Path
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse
from sqlalchemy.exc import SQLAlchemyError
from starlette.middleware.trustedhost import TrustedHostMiddleware

from .api import auth, market, workspace
from .api.dependencies import require_user
from .core.config import get_settings
from .core.numbers import DataError
from .core.runtime import DARK_FLOW_STOP, QUOTE_POOL
from .db.session import get_engine

logger = logging.getLogger("gupiao")


@asynccontextmanager
async def lifespan(application):
    yield
    DARK_FLOW_STOP.set()
    QUOTE_POOL.shutdown(wait=False, cancel_futures=True)
    if get_engine.cache_info().currsize:
        get_engine().dispose()


def create_app():
    settings = get_settings()
    application = FastAPI(
        title="竞观行情API", version="2.0.0", lifespan=lifespan,
        docs_url="/api/docs" if settings.app_env == "development" else None,
        redoc_url=None,
        openapi_url="/api/openapi.json" if settings.app_env == "development" else None,
    )
    application.add_middleware(TrustedHostMiddleware, allowed_hosts=[host.strip() for host in settings.allowed_hosts.split(",")])

    if settings.app_mode == "local":
        def require_local_access(request: Request):
            if not request.client or request.client.host not in {"127.0.0.1", "::1"}:
                raise HTTPException(403, "免登录模式仅供本机访问")
        application.dependency_overrides[require_user] = require_local_access

    @application.middleware("http")
    async def security_headers(request: Request, call_next):
        if request.method in {"POST", "PUT", "PATCH", "DELETE"}:
            if request.headers.get("origin") != settings.public_origin:
                return JSONResponse({"error": "请求来源不被允许"}, status_code=403)
            if request.headers.get("content-type", "").split(";")[0].strip().lower() != "application/json":
                return JSONResponse({"error": "仅接受JSON请求"}, status_code=415)
            body = bytearray()
            async for chunk in request.stream():
                body.extend(chunk)
                if len(body) > 262144:
                    return JSONResponse({"error": "请求内容过大"}, status_code=413)
            request._body = bytes(body)
        response = await call_next(request)
        response.headers["Cache-Control"] = "no-store"
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
        if request.url.path.startswith("/api/"):
            response.headers["Content-Security-Policy"] = "default-src 'none'; frame-ancestors 'none'; base-uri 'none'"
        else:
            response.headers["Content-Security-Policy"] = "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; object-src 'none'"
        return response

    @application.exception_handler(HTTPException)
    async def http_error(request, error):
        return JSONResponse({"error": error.detail}, status_code=error.status_code, headers=error.headers)

    @application.exception_handler(RequestValidationError)
    async def validation_error(request, error):
        return JSONResponse({"error": "请求数据无效，请检查字段、分组与自选数量"}, status_code=422)

    @application.exception_handler(ValueError)
    async def invalid_argument(request, error):
        return JSONResponse({"error": "证券代码或请求参数无效"}, status_code=400)

    @application.exception_handler(DataError)
    async def upstream_error(request, error):
        return JSONResponse({"error": str(error)}, status_code=502)

    @application.exception_handler(SQLAlchemyError)
    async def database_error(request, error):
        logger.error("数据库操作失败: %s", type(error).__name__)
        return JSONResponse({"error": "数据库暂不可用或尚未初始化，本次操作未确认保存；请恢复连接后重新加载"}, status_code=503)

    @application.exception_handler(Exception)
    async def unexpected_error(request, error):
        logger.error("请求处理失败: %s", type(error).__name__)
        return JSONResponse({"error": "服务处理失败，请稍后重试"}, status_code=500)

    @application.get("/api/health")
    def health():
        return {"status": "ok", "server_time": time.time(), "auction_verified": False, "version": "2.0.0", "note": "进程健康不代表数据库、上游行情或实时性已验证"}

    @application.get("/api/runtime")
    def runtime():
        return {"mode": settings.app_mode, "storage": "browser" if settings.app_mode == "local" else "mysql"}

    if settings.app_mode != "local":
        application.include_router(auth.router)
        application.include_router(workspace.router)
    application.include_router(market.router)

    if settings.app_mode == "local":
        distribution = Path(__file__).resolve().parents[2] / "frontend" / "dist"

        @application.get("/")
        def local_index(request: Request):
            require_local_access(request)
            index = distribution / "index.html"
            if not index.is_file():
                return JSONResponse({"error": "前端尚未构建，请先运行 start-local.ps1，或在frontend执行npm run build"}, status_code=503)
            return FileResponse(index)

        @application.get("/assets/{asset_path:path}")
        def local_asset(request: Request, asset_path: str):
            require_local_access(request)
            assets = (distribution / "assets").resolve()
            asset = (assets / asset_path).resolve()
            if not asset.is_relative_to(assets) or not asset.is_file() or asset.suffix not in {".js", ".css", ".svg", ".png", ".jpg", ".webp", ".woff", ".woff2", ".ttf"}:
                raise HTTPException(404, "资源不存在")
            return FileResponse(asset)
    return application


app = create_app()
