import argparse
import getpass
import re
import uuid
from datetime import datetime

from sqlalchemy import delete, select, text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from .core.security import password_hash
from .db.models import User, UserSession, UserSettings, WatchlistGroup, WorkspaceMeta
from .db.session import get_engine


def main():
    parser = argparse.ArgumentParser(description="竞观账户管理，不提供默认密码或公开注册")
    parser.add_argument("command", choices=["create-user", "reset-password", "database-check"])
    parser.add_argument("--username")
    args = parser.parse_args()
    if args.command != "database-check" and (not args.username or not re.fullmatch(r"[A-Za-z0-9_.-]{3,64}", args.username)):
        parser.error("请通过--username指定3至64位字母、数字、点、横线或下划线用户名")
    try:
        with Session(get_engine()) as database:
            if args.command == "database-check":
                database.execute(text("SELECT 1"))
                revision = database.execute(text("SELECT version_num FROM alembic_version")).scalar_one()
                print(f"数据库可连接，迁移版本：{revision}")
                return
            username = args.username.lower()
            user = database.scalar(select(User).where(User.username == username))
            if args.command == "create-user" and user:
                parser.exit(1, "用户名已存在，未修改账户\n")
            if args.command == "reset-password" and not user:
                parser.exit(1, "账户不存在\n")
            password = getpass.getpass("请输入12至128位新密码：")
            if len(password) < 12 or len(password) > 128 or not password.strip():
                parser.exit(1, "密码长度必须为12至128，且不能全部为空白\n")
            if password != getpass.getpass("再次输入密码："):
                parser.exit(1, "两次密码不一致，未修改\n")
            now = datetime.utcnow()
            if user:
                user.password_hash = password_hash(password)
                database.execute(delete(UserSession).where(UserSession.user_id == user.id))
            else:
                user = User(id=str(uuid.uuid4()), username=username, password_hash=password_hash(password), active=True, created_at=now)
                database.add(user)
                database.flush()
                database.add(WorkspaceMeta(user_id=user.id, revision=0, updated_at=now))
                database.add(UserSettings(user_id=user.id, view="list", layout=6))
                database.add_all([WatchlistGroup(user_id=user.id, id=group_id, name=name, position=position) for position, (group_id, name) in enumerate([("focus", "重点观察"), ("watch", "观察名单")])])
            database.commit()
            print("账户操作成功；重置密码时已撤销旧会话")
    except SQLAlchemyError:
        parser.exit(1, "数据库连接或表结构异常。请检查配置并先执行显式数据库迁移，未输出连接凭证。\n")


if __name__ == "__main__":
    main()
