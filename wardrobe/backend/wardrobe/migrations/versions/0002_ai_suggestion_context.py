"""AI 建议来源上下文（Phase 5A-1）

Revision ID: 0002
Revises: 0001
Create Date: 2026-10-27

与 change_proposal 一对一的支持表，保存「本地图片颜色分析」生成提议时的可审计来源：
图片 ID 与不可变的 SHA256、生成时目标 version、分析区域、算法版本与参数、选中的候选。
不修改 0001 的任何表；历史提议没有上下文，继续按原规则处理。

* proposal_id 随提议删除（ON DELETE CASCADE）。当前代码不会删除提议，只改状态。
* image_id 在图片记录删除时置空（ON DELETE SET NULL），因此历史分析上下文不会阻止图片删除与文件清理；
  image_sha256 保留审计事实。带上下文的提议在图片已删除时接受会返回 PROPOSAL_STALE。
"""

from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None

# 与 0001 的建表 SQL 同样的排版，docs/schema.sql 由此直接生成
CREATE_TABLE = """CREATE TABLE ai_suggestion_context (
    proposal_id     INTEGER PRIMARY KEY REFERENCES change_proposal(id) ON DELETE CASCADE,
    kind            TEXT NOT NULL CHECK (kind IN ('color')),
    target_version  INTEGER NOT NULL,
    image_id        INTEGER REFERENCES image(id) ON DELETE SET NULL,
    image_sha256    TEXT NOT NULL,
    region          TEXT,
    algorithm       TEXT NOT NULL,
    parameters      TEXT NOT NULL,
    candidate       TEXT NOT NULL,
    candidates      TEXT NOT NULL,
    created_at      TEXT NOT NULL
)"""


def upgrade() -> None:
    op.execute(CREATE_TABLE)
    op.execute("CREATE INDEX ix_ai_context_image ON ai_suggestion_context(image_id)")


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_ai_context_image")
    op.execute("DROP TABLE IF EXISTS ai_suggestion_context")
