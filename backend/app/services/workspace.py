from datetime import datetime

from fastapi import HTTPException
from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError

from ..db.models import UserSettings, WatchlistGroup, WatchlistStock, WorkspaceMeta


def load_workspace(database, user_id):
    meta = database.get(WorkspaceMeta, user_id)
    settings = database.get(UserSettings, user_id)
    if meta is None or settings is None:
        raise HTTPException(503, "账户工作台尚未初始化，请联系管理员")
    groups = database.scalars(select(WatchlistGroup).where(WatchlistGroup.user_id == user_id).order_by(WatchlistGroup.position)).all()
    stocks = database.scalars(select(WatchlistStock).where(WatchlistStock.user_id == user_id).order_by(WatchlistStock.position)).all()
    return {
        "revision": meta.revision,
        "groups": [{"id": group.id, "name": group.name} for group in groups],
        "stocks": [{"id": f"{stock.market}.{stock.code}", "market": stock.market, "code": stock.code, "name": stock.name, "group": stock.group_id} for stock in stocks],
        "settings": {"view": settings.view, "layout": settings.layout},
    }


def save_workspace(database, user_id, payload):
    meta = database.scalar(select(WorkspaceMeta).where(WorkspaceMeta.user_id == user_id).with_for_update())
    if meta is None:
        raise HTTPException(503, "账户工作台尚未初始化")
    if meta.revision != payload.expected_revision:
        database.rollback()
        raise HTTPException(409, "其他设备已修改自选，请重新加载后再操作；本次修改未保存")
    try:
        database.execute(delete(WatchlistStock).where(WatchlistStock.user_id == user_id))
        database.execute(delete(WatchlistGroup).where(WatchlistGroup.user_id == user_id))
        database.add_all([WatchlistGroup(user_id=user_id, id=group.id, name=group.name, position=position) for position, group in enumerate(payload.groups)])
        database.flush()
        database.add_all([WatchlistStock(user_id=user_id, market=stock.market, code=stock.code, name=stock.name, group_id=stock.group, position=position) for position, stock in enumerate(payload.stocks)])
        settings = database.get(UserSettings, user_id)
        if settings is None:
            raise HTTPException(503, "账户设置尚未初始化")
        settings.view = payload.settings.view
        settings.layout = payload.settings.layout
        meta.revision += 1
        meta.updated_at = datetime.utcnow()
        database.flush()
        result = {"revision": meta.revision, "groups": [group.model_dump() for group in payload.groups], "stocks": [stock.model_dump() for stock in payload.stocks], "settings": payload.settings.model_dump()}
        database.commit()
        return result
    except IntegrityError:
        database.rollback()
        raise HTTPException(409, "分组名称冲突或数据已改变，本次修改未保存") from None
