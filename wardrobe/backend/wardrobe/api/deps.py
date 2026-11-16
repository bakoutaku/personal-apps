from typing import Annotated

from fastapi import Depends, Header, Request
from sqlalchemy.orm import Session

from ..config import Settings
from ..db import session_dependency
from ..services.common import actor_of

SessionDep = Annotated[Session, Depends(session_dependency)]


def _actor(request: Request) -> str:
    return actor_of(request)


def _settings(request: Request) -> Settings:
    return request.app.state.settings


ActorDep = Annotated[str, Depends(_actor)]
SettingsDep = Annotated[Settings, Depends(_settings)]
IfMatch = Annotated[str | None, Header(alias="If-Match", description="当前 version，可替代 body 中的 version")]


def paging(limit: int = 50, offset: int = 0) -> tuple[int, int]:
    return max(1, min(limit, 200)), max(0, offset)


PagingDep = Annotated[tuple[int, int], Depends(paging)]


def page(items: list, total: int, limit: int, offset: int) -> dict:
    return {"items": items, "total": total, "limit": limit, "offset": offset}
