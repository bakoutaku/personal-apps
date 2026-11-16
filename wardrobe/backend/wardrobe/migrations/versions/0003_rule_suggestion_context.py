"""规则建议来源上下文（Phase 5C）

Revision ID: 0003
Revises: 0002
Create Date: 2026-10-27

与 change_proposal 一对一的支持表，保存 Phase 5C「标签 / 分类建议」生成提议时的可审计依据：
规则版本、生成时目标 version、证据（相似衣物、同商品衣物、命中的名称关键词等）。
与 0002 的 ai_suggestion_context（照片颜色分析专用，含图片 SHA）分开；不修改既有表。
"""

from alembic import op

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None

CREATE_TABLE = """CREATE TABLE rule_suggestion_context (
    proposal_id     INTEGER PRIMARY KEY REFERENCES change_proposal(id) ON DELETE CASCADE,
    kind            TEXT NOT NULL CHECK (kind IN ('tags','category')),
    target_version  INTEGER NOT NULL,
    algorithm       TEXT NOT NULL,
    evidence        TEXT NOT NULL,
    created_at      TEXT NOT NULL
)"""


def upgrade() -> None:
    op.execute(CREATE_TABLE)


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS rule_suggestion_context")
