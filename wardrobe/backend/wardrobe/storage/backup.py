"""备份与恢复（ARCHITECTURE §8）。

备份 zip 内容：
  wardrobe.db       SQLite 在线备份 API 生成的一致性快照
  images/...        快照中 image 表引用的原图与缩略图
  manifest.json     版本、schema revision、各表行数、全部文件 sha256

图片文件内容寻址且不可变，只按快照里的 image 记录打包，所以数据库与图片天然一致。
"""

import hashlib
import json
import shutil
import sqlite3
import tempfile
import zipfile
from contextlib import closing
from datetime import datetime
from pathlib import Path, PurePosixPath

from .. import __version__
from ..config import Settings
from ..db import expected_schema, known_revisions, table_columns
from .images import image_lock

MANIFEST = "manifest.json"
DB_NAME = "wardrobe.db"
FORMAT = "wardrobe.backup/v1"


class BackupError(Exception):
    pass


def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _snapshot_db(src: Path, dest: Path) -> None:
    with closing(sqlite3.connect(src)) as s, closing(sqlite3.connect(dest)) as d:
        s.backup(d)
        # 快照改为普通回滚日志模式：备份中的 wardrobe.db 是自包含的单个文件，
        # 打开或修改它时不会产生不在备份里的 -wal 文件。恢复后服务连接时会重新切换为 WAL。
        d.execute("PRAGMA journal_mode = DELETE")


def _db_info(db: Path) -> tuple[str | None, dict[str, int], list[tuple[str, str]]]:
    with closing(sqlite3.connect(db)) as conn:
        try:
            rev = conn.execute("SELECT version_num FROM alembic_version").fetchone()
        except sqlite3.OperationalError:
            rev = None
        tables = [
            r[0]
            for r in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' "
                "AND name NOT LIKE 'search_index_%' ORDER BY name"
            )
        ]
        counts = {t: conn.execute(f'SELECT count(*) FROM "{t}"').fetchone()[0] for t in tables}
        images = conn.execute("SELECT storage_path, thumb_path FROM image").fetchall() if "image" in tables else []
    return (rev[0] if rev else None), counts, images


def create_backup(settings: Settings, reason: str = "manual") -> Path:
    if not settings.db_path.exists():
        raise BackupError("数据库不存在，没有可备份的数据")
    settings.backups_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S-%f")
    target = settings.backups_dir / f"wardrobe-{stamp}-{reason}.zip"

    # 持有图片锁：打包期间 GC 不会删除快照中引用的文件
    with image_lock(settings), tempfile.TemporaryDirectory(dir=settings.data_dir) as tmp:
        snap = Path(tmp) / DB_NAME
        _snapshot_db(settings.db_path, snap)
        revision, counts, images = _db_info(snap)

        files: dict[str, str] = {DB_NAME: _sha256_file(snap)}
        image_files: list[tuple[str, Path]] = []
        for rel in sorted({p for pair in images for p in pair}):
            src = settings.images_dir / rel
            if not src.exists():
                raise BackupError(f"图片文件缺失：{rel}")
            arc = f"images/{rel}"
            files[arc] = _sha256_file(src)
            image_files.append((arc, src))

        manifest = {
            "format": FORMAT,
            "app_version": __version__,
            "schema_revision": revision,
            "created_at": datetime.now().astimezone().isoformat(timespec="seconds"),
            "reason": reason,
            "table_counts": counts,
            "files": files,
        }
        partial = target.with_suffix(".zip.partial")
        with zipfile.ZipFile(partial, "w", zipfile.ZIP_DEFLATED) as zf:
            zf.write(snap, DB_NAME)
            for arc, src in image_files:
                zf.write(src, arc, compress_type=zipfile.ZIP_STORED)
            zf.writestr(MANIFEST, json.dumps(manifest, ensure_ascii=False, indent=2))
        partial.replace(target)

    prune_backups(settings)
    return target


def list_backups(settings: Settings) -> list[dict]:
    if not settings.backups_dir.exists():
        return []
    out = []
    for f in sorted(settings.backups_dir.glob("wardrobe-*.zip"), reverse=True):
        out.append({"name": f.name, "bytes": f.stat().st_size})
    return out


def prune_backups(settings: Settings) -> None:
    backups = sorted(settings.backups_dir.glob("wardrobe-*.zip"))
    for old in backups[: max(0, len(backups) - settings.backup_keep)]:
        old.unlink(missing_ok=True)


def _safe_member(name: str) -> bool:
    p = PurePosixPath(name)
    return not p.is_absolute() and ".." not in p.parts and "\\" not in name and name == p.as_posix()


RESTORE_MARKER = ".restore-in-progress"


def _check_database(db: Path, manifest: dict, extract_to: Path) -> None:
    """以只读方式打开备份数据库，按数据库内容（而不是 manifest）核对结构与图片引用。"""
    if not db.is_file() or db.stat().st_size == 0:
        raise BackupError("备份缺少数据库文件 wardrobe.db")
    try:
        conn = sqlite3.connect(f"{db.resolve().as_uri()}?mode=ro", uri=True)
    except sqlite3.Error as exc:
        raise BackupError(f"无法打开备份数据库：{exc}") from exc
    with closing(conn):
        try:
            if conn.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                raise BackupError("备份中的数据库 integrity_check 未通过")
            if conn.execute("PRAGMA foreign_key_check").fetchall():
                raise BackupError("备份中的数据库存在外键不一致")
            actual_schema = table_columns(conn)
            if "alembic_version" not in actual_schema:
                raise BackupError("备份数据库缺少 alembic_version 表，无法确定 schema 版本")
            rows = conn.execute("SELECT version_num FROM alembic_version").fetchall()
            if len(rows) != 1:
                raise BackupError("备份数据库没有有效的 schema 版本记录")
            actual = rows[0][0]
            if actual not in known_revisions():
                raise BackupError(f"备份的 schema 版本 {actual!r} 比当前程序新或未知，请先升级程序")
            if manifest.get("schema_revision") != actual:
                raise BackupError(
                    f"manifest 的 schema 版本 {manifest.get('schema_revision')!r} 与数据库实际版本 {actual!r} 不一致"
                )
            # 必要的表与列由迁移执行到该版本推导，而不是手工维护清单（BUG-004 复查补充）
            expected = expected_schema(actual)
            missing_tables = sorted(set(expected) - set(actual_schema))
            if missing_tables:
                raise BackupError(f"备份数据库缺少 schema {actual} 的必要表：{missing_tables}")
            wrong_columns = sorted(t for t in expected if actual_schema[t] != expected[t])
            if wrong_columns:
                raise BackupError(f"备份数据库中这些表的列与 schema {actual} 不一致：{wrong_columns}")
            counts = manifest.get("table_counts")
            if not isinstance(counts, dict):
                raise BackupError("manifest 缺少 table_counts")
            actual_counts = {
                t: conn.execute(f'SELECT count(*) FROM "{t}"').fetchone()[0]
                for t in actual_schema
                if not t.startswith("search_index_")
            }
            if counts != actual_counts:
                diff = sorted(t for t in set(counts) | set(actual_counts) if counts.get(t) != actual_counts.get(t))
                raise BackupError(f"manifest 的表行数与数据库不一致：{diff}")
            images = conn.execute("SELECT id, sha256, storage_path, thumb_path FROM image").fetchall()
        except sqlite3.DatabaseError as exc:
            raise BackupError(f"备份数据库无法读取：{exc}") from exc

    files = manifest.get("files", {})
    for image_id, sha, storage_path, thumb_path in images:
        for kind, rel in (("原图", storage_path), ("缩略图", thumb_path)):
            prefix = "original/" if kind == "原图" else "thumb/"
            if not rel or not _safe_member(rel) or not rel.startswith(prefix):
                raise BackupError(f"图片 {image_id} 的{kind}路径不安全：{rel!r}")
            arc = f"images/{rel}"
            if arc not in files or not (extract_to / arc).is_file():
                raise BackupError(f"备份缺少图片 {image_id} 的{kind}：{arc}")
        if _sha256_file(extract_to / "images" / storage_path) != sha:
            raise BackupError(f"图片 {image_id} 的原图内容与数据库记录的 sha256 不一致")


def verify_backup(zip_path: Path, extract_to: Path) -> dict:
    """校验并解压到 extract_to。任何异常都不触碰现有数据。

    manifest 只是待校验的输入：除了核对 manifest 与 zip 内容一致，还以只读方式打开数据库，
    检查必要的表、实际 schema 版本，以及数据库引用的每个图片文件都存在且内容正确。
    """
    try:
        zf = zipfile.ZipFile(zip_path)
    except (zipfile.BadZipFile, FileNotFoundError, IsADirectoryError) as exc:
        raise BackupError(f"不是有效的备份文件：{zip_path}") from exc
    with zf:
        names = zf.namelist()
        for n in names:
            if not _safe_member(n):
                raise BackupError(f"备份中含有不安全的路径：{n!r}")
        if len(set(names)) != len(names):
            raise BackupError("备份中含有重复的文件名")
        if MANIFEST not in names:
            raise BackupError("备份缺少 manifest.json")
        if DB_NAME not in names:
            raise BackupError("备份缺少数据库文件 wardrobe.db")
        try:
            manifest = json.loads(zf.read(MANIFEST))
        except ValueError as exc:
            raise BackupError("manifest.json 不是合法 JSON") from exc
        if manifest.get("format") != FORMAT:
            raise BackupError(f"不支持的备份格式：{manifest.get('format')!r}")
        expected = manifest.get("files", {})
        if not isinstance(expected, dict):
            raise BackupError("manifest.files 格式错误")
        extra = set(names) - set(expected) - {MANIFEST}
        missing = set(expected) - set(names)
        if extra or missing:
            raise BackupError(f"备份文件清单不一致：多余 {sorted(extra)}，缺少 {sorted(missing)}")
        zf.extractall(extract_to)

    for rel, digest in expected.items():
        if _sha256_file(extract_to / rel) != digest:
            raise BackupError(f"文件校验失败：{rel}")
    _check_database(extract_to / DB_NAME, manifest, extract_to)
    return manifest


def check_no_interrupted_restore(settings: Settings) -> None:
    """启动前检查：若上次恢复中断，拒绝启动，避免在空位置静默新建数据库。"""
    marker = settings.data_dir / RESTORE_MARKER
    leftovers = sorted(p.name for p in settings.data_dir.glob(".restore-old-*"))
    if marker.exists() or (leftovers and not settings.db_path.exists()):
        raise BackupError(
            "检测到未完成的恢复操作，为避免覆盖数据已停止启动。"
            f"请检查数据目录 {settings.data_dir} 中的 {', '.join(leftovers) or RESTORE_MARKER}，"
            f"把其中的 wardrobe.db 与 images 移回原位后删除 {RESTORE_MARKER}。"
        )


def restore_backup(settings: Settings, zip_path: Path) -> dict:
    """调用方须确保服务已停止。恢复前自动备份当前数据，然后用 rename 替换。

    从搬走旧数据的第一步起，每一步都记录下来；任何一步失败都按实际完成的步骤逆序回滚，
    回滚后数据目录与恢复前完全一致。
    """
    settings.ensure_dirs()
    check_no_interrupted_restore(settings)
    staging = Path(tempfile.mkdtemp(prefix=".restore-", dir=settings.data_dir))
    try:
        manifest = verify_backup(zip_path, staging)
        pre_backup = create_backup(settings, "pre-restore") if settings.db_path.exists() else None

        marker = settings.data_dir / RESTORE_MARKER
        old = settings.data_dir / f".restore-old-{datetime.now().strftime('%Y%m%d-%H%M%S-%f')}"
        moved: list[tuple[Path, Path]] = []  # (原位置, 暂存位置)
        installed: list[Path] = []
        marker.write_text(json.dumps({"backup": zip_path.name, "old_dir": old.name}), encoding="utf-8")
        try:
            old.mkdir()
            for name in (DB_NAME, f"{DB_NAME}-wal", f"{DB_NAME}-shm"):
                src = settings.data_dir / name
                if src.exists():
                    src.replace(old / name)
                    moved.append((src, old / name))
            if settings.images_dir.exists():
                settings.images_dir.replace(old / "images")
                moved.append((settings.images_dir, old / "images"))

            (staging / DB_NAME).replace(settings.db_path)
            installed.append(settings.db_path)
            if (staging / "images").exists():
                (staging / "images").replace(settings.images_dir)
            else:
                settings.images_dir.mkdir()
            installed.append(settings.images_dir)
        except BaseException:
            for path in reversed(installed):
                if path.is_dir():
                    shutil.rmtree(path)
                else:
                    path.unlink(missing_ok=True)
            for original, temp in reversed(moved):
                temp.replace(original)
            if old.exists() and not any(old.iterdir()):
                old.rmdir()
            marker.unlink(missing_ok=True)
            raise
        marker.unlink()
        shutil.rmtree(old, ignore_errors=True)
    finally:
        shutil.rmtree(staging, ignore_errors=True)
    return {"restored_from": zip_path.name, "pre_restore_backup": pre_backup.name if pre_backup else None, **manifest}
