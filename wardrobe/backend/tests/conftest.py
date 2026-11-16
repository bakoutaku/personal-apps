"""测试夹具：每个测试使用独立的临时数据目录和数据库，绝不触碰 data/ 中的正式数据。"""

import pytest
from fastapi.testclient import TestClient

from wardrobe.config import Settings
from wardrobe.main import create_app

BASE_URL = "http://127.0.0.1:8765"


@pytest.fixture
def settings(tmp_path) -> Settings:
    return Settings(data_dir=tmp_path / "data")


@pytest.fixture
def app(settings):
    return create_app(settings)


def _client(app, client_name: str | None) -> TestClient:
    headers = {"X-Wardrobe-Client": client_name} if client_name else {}
    return TestClient(app, base_url=BASE_URL, headers=headers)


@pytest.fixture
def client(app) -> TestClient:
    """人工操作（web-ui），可修改已核实记录。"""
    return _client(app, "web-ui")


@pytest.fixture
def ai(app) -> TestClient:
    """AI 请求方，受核实保护限制。"""
    return _client(app, "ai:codex")


@pytest.fixture
def raw(app) -> TestClient:
    """不带 X-Wardrobe-Client 头。"""
    return _client(app, None)
