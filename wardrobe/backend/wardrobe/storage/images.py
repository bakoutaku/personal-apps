"""图片存储（ARCHITECTURE §7）。

* 内容寻址：original/ab/<sha256>.<ext>，thumb/ab/<sha256>.webp（3:4，宽 600）
* 文件只在「没有任何 image 记录引用」时由 gc_orphans() 删除，且在数据库提交之后执行，
  因此数据库回滚永远不会导致文件丢失（DATA_MODEL 5.1）。
* 上传（写文件 → 写记录 → 提交）与 GC（查询引用 → 删除文件）共用 image_lock()，
  这是 flock 文件锁，同一进程的不同线程和独立的 CLI 进程之间都互斥，
  因此 GC 不会基于过期的引用快照删除刚被重新上传的文件。
"""

import fcntl
import hashlib
import io
import os
import tempfile
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path

from PIL import Image as PILImage
from PIL import ImageOps, UnidentifiedImageError
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from ..config import Settings
from ..models import Image

ALLOWED_FORMATS = {"JPEG": ("image/jpeg", "jpg"), "PNG": ("image/png", "png"), "WEBP": ("image/webp", "webp")}
THUMB_SIZE = (600, 800)
PILImage.MAX_IMAGE_PIXELS = 60_000_000  # 防解压炸弹
# Pillow 只在超过 2 × MAX_IMAGE_PIXELS 时抛错，介于 1～2 倍之间只给警告；上传时自己按上限检查
INTEGER_MODES = ("I", "I;16", "I;16L", "I;16B", "I;16N")


class ImageRejected(ValueError):
    pass


@dataclass
class StoredImage:
    sha256: str
    mime: str
    width: int
    height: int
    bytes: int
    storage_path: str
    thumb_path: str


def _atomic_write(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=".tmp-")
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(data)
        os.replace(tmp, path)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise


def store_image(settings: Settings, data: bytes) -> StoredImage:
    """校验并写入原图与缩略图。已存在相同内容时直接复用文件。"""
    if len(data) > settings.max_upload_bytes:
        raise ImageRejected(f"文件超过 {settings.max_upload_bytes // (1024 * 1024)} MB 上限")
    try:
        with PILImage.open(io.BytesIO(data)) as probe:
            fmt = probe.format
            # 只读文件头就能得到尺寸；在解码之前拒绝，避免为超限图片分配内存
            pixels = probe.size[0] * probe.size[1]
            if pixels > PILImage.MAX_IMAGE_PIXELS:
                raise ImageRejected(
                    f"图片像素数 {pixels:,} 超过上限 {PILImage.MAX_IMAGE_PIXELS:,}（约 6000 万像素），请缩小后再上传"
                )
            probe.verify()
        img = PILImage.open(io.BytesIO(data))
        img.load()
    except (UnidentifiedImageError, OSError, SyntaxError, PILImage.DecompressionBombError) as exc:
        raise ImageRejected("无法识别为图片，或图片已损坏") from exc
    if fmt not in ALLOWED_FORMATS:
        raise ImageRejected(f"不支持的图片格式 {fmt}，仅支持 JPEG / PNG / WebP")

    mime, ext = ALLOWED_FORMATS[fmt]
    sha = hashlib.sha256(data).hexdigest()
    rel_original = f"original/{sha[:2]}/{sha}.{ext}"
    rel_thumb = f"thumb/{sha[:2]}/{sha}.webp"
    original = settings.images_dir / rel_original
    thumb = settings.images_dir / rel_thumb

    if not original.exists():
        _atomic_write(original, data)
    if not thumb.exists():
        # exif_transpose 修正方向；重新编码为 WebP 会丢弃 EXIF（含 GPS）
        oriented = to_8bit(ImageOps.exif_transpose(img)).convert("RGB")
        fitted = ImageOps.fit(oriented, THUMB_SIZE, method=PILImage.Resampling.LANCZOS)
        buf = io.BytesIO()
        fitted.save(buf, "WEBP", quality=82)
        _atomic_write(thumb, buf.getvalue())
    width, height = ImageOps.exif_transpose(img).size
    return StoredImage(sha, mime, width, height, len(data), rel_original, rel_thumb)


def to_8bit(img: PILImage.Image) -> PILImage.Image:
    """16 位灰度等整数模式直接转 RGB 会截断到 255（全部变白）；按 0～65535 线性缩到 8 位灰度。"""
    if img.mode in INTEGER_MODES:
        return img.convert("I").point(lambda v: v * (1 / 256)).convert("L")
    return img


def media_url(rel_path: str) -> str:
    return f"/media/{rel_path}"


@contextmanager
def image_lock(settings: Settings) -> Iterator[None]:
    """图片文件生命周期锁。持有期间不要再获取数据库写锁（上传是先写锁后图片锁，GC 只读）。"""
    settings.run_dir.mkdir(parents=True, exist_ok=True)
    with open(settings.run_dir / "images.lock", "a+") as fd:
        fcntl.flock(fd, fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(fd, fcntl.LOCK_UN)


def _image_files(settings: Settings) -> list[Path]:
    files = []
    for sub in ("original", "thumb"):
        base = settings.images_dir / sub
        if base.exists():
            files.extend(f for f in base.glob("*/*") if not f.name.startswith(".tmp-"))
    return files


def gc_orphans(settings: Settings, factory: sessionmaker[Session], only_sha: set[str] | None = None) -> int:
    """删除没有 image 记录引用的文件。

    必须在相关数据库修改提交之后调用。先列出候选文件，再在 image_lock 内用新的只读会话
    查询当前引用，最后删除；查询与删除之间不会有上传提交。
    """
    candidates = [f for f in _image_files(settings) if only_sha is None or f.stem in only_sha]
    if not candidates:
        return 0
    removed = 0
    with image_lock(settings), factory() as session:
        referenced = set(session.scalars(select(Image.sha256).where(Image.sha256.in_({f.stem for f in candidates}))))
        for f in candidates:
            if f.stem in referenced:
                continue
            try:
                f.unlink()
                removed += 1
            except FileNotFoundError:
                pass
            except OSError:
                pass  # 下次启动或 gc-images 时重试
    return removed
