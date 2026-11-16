"""运行配置。全部来自环境变量 WARDROBE_*，测试中直接构造 Settings。"""

import os
from dataclasses import dataclass, field
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
LOOPBACK_HOST = "127.0.0.1"


@dataclass(frozen=True)
class Settings:
    data_dir: Path
    port: int = 8765
    max_upload_bytes: int = 20 * 1024 * 1024
    backup_keep: int = 20
    # 开发时 Vite dev server 的来源；生产模式同源，不需要
    extra_origins: tuple[str, ...] = field(default=("http://127.0.0.1:5173", "http://localhost:5173"))
    # 构建好的网页界面（npm run build 的输出）；不存在时根路径显示说明页
    frontend_dist: Path = field(default=REPO_ROOT / "frontend" / "dist")

    @property
    def host(self) -> str:
        return LOOPBACK_HOST

    @property
    def db_path(self) -> Path:
        return self.data_dir / "wardrobe.db"

    @property
    def images_dir(self) -> Path:
        return self.data_dir / "images"

    @property
    def backups_dir(self) -> Path:
        return self.data_dir / "backups"

    @property
    def run_dir(self) -> Path:
        return self.data_dir / "run"

    @property
    def pid_file(self) -> Path:
        return self.run_dir / "wardrobe.pid"

    @property
    def log_file(self) -> Path:
        return self.run_dir / "server.log"

    @property
    def allowed_hosts(self) -> frozenset[str]:
        return frozenset({f"127.0.0.1:{self.port}", f"localhost:{self.port}"})

    @property
    def allowed_origins(self) -> frozenset[str]:
        return frozenset({f"http://127.0.0.1:{self.port}", f"http://localhost:{self.port}", *self.extra_origins})

    def ensure_dirs(self) -> None:
        for d in (self.data_dir, self.images_dir, self.backups_dir, self.run_dir):
            d.mkdir(parents=True, exist_ok=True)


def load_settings() -> Settings:
    data_dir = Path(os.environ.get("WARDROBE_DATA_DIR", REPO_ROOT / "data")).expanduser().resolve()
    port = int(os.environ.get("WARDROBE_PORT", "8765"))
    return Settings(data_dir=data_dir, port=port)
