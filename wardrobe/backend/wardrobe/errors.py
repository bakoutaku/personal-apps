"""统一错误格式：{"error": {"code", "message", "details"}}。"""

from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from sqlalchemy.exc import IntegrityError
from starlette.exceptions import HTTPException as StarletteHTTPException


class ApiError(Exception):
    def __init__(self, status: int, code: str, message: str, details: list[dict[str, Any]] | None = None):
        super().__init__(message)
        self.status = status
        self.code = code
        self.message = message
        self.details = details or []


def not_found(entity: str, ident: Any) -> ApiError:
    return ApiError(404, "NOT_FOUND", f"{entity} {ident} 不存在")


def validation(loc: list, code: str, message: str, hint: str | None = None) -> ApiError:
    detail: dict[str, Any] = {"loc": loc, "code": code, "message": message}
    if hint:
        detail["hint"] = hint
    return ApiError(422, "VALIDATION_ERROR", message, [detail])


def error_body(code: str, message: str, details: list | None = None) -> dict:
    return {"error": {"code": code, "message": message, "details": details or []}}


def _loc(loc: tuple) -> list:
    # 去掉 FastAPI 自带的 "body"/"query" 前缀，让 loc 直接对应字段路径
    parts = list(loc)
    if parts and parts[0] in ("body", "query", "path", "header", "form"):
        parts = parts[1:]
    return parts


def install_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(ApiError)
    async def _api_error(_req: Request, exc: ApiError):
        return JSONResponse(error_body(exc.code, exc.message, exc.details), status_code=exc.status)

    @app.exception_handler(RequestValidationError)
    async def _validation(_req: Request, exc: RequestValidationError):
        details = []
        for err in exc.errors():
            if err.get("type") == "json_invalid":
                return JSONResponse(error_body("BAD_REQUEST", "请求体不是合法 JSON"), status_code=400)
            details.append({"loc": _loc(err.get("loc", ())), "code": err.get("type"), "message": err.get("msg")})
        return JSONResponse(error_body("VALIDATION_ERROR", f"{len(details)} 个字段校验失败", details), status_code=422)

    @app.exception_handler(StarletteHTTPException)
    async def _http(_req: Request, exc: StarletteHTTPException):
        code = {404: "NOT_FOUND", 405: "METHOD_NOT_ALLOWED", 413: "PAYLOAD_TOO_LARGE"}.get(
            exc.status_code, "HTTP_ERROR"
        )
        return JSONResponse(error_body(code, str(exc.detail)), status_code=exc.status_code)

    @app.exception_handler(IntegrityError)
    async def _integrity(_req: Request, exc: IntegrityError):
        # 服务层应先做业务校验；走到这里说明是数据库层的兜底约束
        return JSONResponse(
            error_body("CONSTRAINT_VIOLATION", "违反数据库约束", [{"message": str(exc.orig)}]), status_code=409
        )
