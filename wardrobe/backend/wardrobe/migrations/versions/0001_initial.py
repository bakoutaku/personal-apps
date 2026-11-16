"""initial schema

Revision ID: 0001
Revises:
Create Date: 2026-10-26
"""

import sqlite3
from pathlib import Path

from alembic import op

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None

SQL_FILE = Path(__file__).with_suffix(".sql")

TABLES = [
    "search_index", "change_log", "change_proposal", "import_row", "outfit_image", "outfit_tag",
    "outfit_item", "outfit", "item_image", "item_tag", "wardrobe_item", "purchase_line", "purchase",
    "product_image", "material_component", "product_size", "product_color", "product_identifier",
    "product", "image", "import_job", "tag", "category", "brand",
]  # fmt: skip


def split_statements(sql: str) -> list[str]:
    statements, buf = [], ""
    for line in sql.splitlines(keepends=True):
        if not buf and line.strip().startswith("--"):
            continue
        buf += line
        if sqlite3.complete_statement(buf):
            statements.append(buf.strip())
            buf = ""
    if buf.strip():
        raise ValueError(f"未结束的 SQL 语句: {buf[:80]}")
    return statements


def upgrade() -> None:
    for stmt in split_statements(SQL_FILE.read_text(encoding="utf-8")):
        op.execute(stmt)


def downgrade() -> None:
    for table in TABLES:
        op.execute(f"DROP TABLE IF EXISTS {table}")
