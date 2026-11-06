from alembic import context

from backend.app.db.models import Base
from backend.app.db.session import get_engine


def run_migrations_online():
    with get_engine().connect() as connection:
        context.configure(connection=connection, target_metadata=Base.metadata, compare_type=True)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    raise RuntimeError("此项目迁移必须连接已授权的目标数据库，请先备份并核对数据库名称")
else:
    run_migrations_online()
