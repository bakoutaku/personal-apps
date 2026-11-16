"""Alembic 环境。连接由 wardrobe.db.run_migrations 通过 config.attributes 传入。"""

from alembic import context

connection = context.config.attributes.get("connection")
if connection is None:
    raise RuntimeError("请通过 `./wardrobe migrate` 执行迁移（需要由应用提供数据库连接）")

context.configure(connection=connection, target_metadata=None, render_as_batch=True)
with context.begin_transaction():
    context.run_migrations()
