import json
import re
import threading
import time
from collections import defaultdict
from concurrent.futures import FIRST_COMPLETED, wait
from datetime import datetime, timedelta

from ..core.cache import cached
from ..core.numbers import DataError, finite_number, source_timestamp, validate_secid
from ..core.runtime import (
    ROOT, SHANGHAI, QUOTE_POOL, WATCHLIST_LIMIT,
    DARK_FLOW_LOCK, DARK_FLOW_STOP, DARK_FLOW_STATE,
)
from ..providers.eastmoney import eastmoney_data
from ..providers.http import request_json


def load_trends(secid):
    data = eastmoney_data(
        "https://push2his.eastmoney.com/api/qt/stock/trends2/get",
        {
            "secid": secid,
            "fields1": "f1,f2,f3,f4,f5,f6,f7,f8,f9,f10,f11,f12,f13",
            "fields2": "f51,f52,f53,f54,f55,f56,f57,f58",
            "iscr": "1",
            "ndays": "1",
        },
    )
    if str(data.get("code")) != secid.split(".", 1)[1]:
        raise DataError("分时数据的证券代码不匹配")
    rows = data.get("trends")
    if not isinstance(rows, list):
        raise DataError("数据源没有返回分时记录")
    points = []
    auction_points = []
    preopen_result_points = []
    latest_date = None
    for row in rows:
        if not isinstance(row, str):
            continue
        fields = row.split(",")
        if len(fields) < 8:
            continue
        try:
            moment = datetime.strptime(fields[0], "%Y-%m-%d %H:%M").replace(tzinfo=SHANGHAI)
        except ValueError:
            continue
        if source_timestamp(moment.timestamp()) is None:
            continue
        latest_date = max(latest_date, moment.date()) if latest_date else moment.date()
        clock_minutes = moment.hour * 60 + moment.minute
        if not (555 <= clock_minutes <= 690 or 780 <= clock_minutes <= 900):
            continue
        price = finite_number(fields[2])
        if price is None or price <= 0:
            continue
        volume = finite_number(fields[5])
        point = {
            "minute": clock_minutes,
            "timestamp": int(moment.timestamp()),
            "price": price,
            "volume": volume if volume is not None and volume >= 0 else None,
        }
        if clock_minutes <= 565:
            auction_points.append(point)
        elif clock_minutes < 570:
            preopen_result_points.append(point)
        else:
            point["minute"] = clock_minutes - 570 if clock_minutes <= 690 else clock_minutes - 660
            points.append(point)

    def latest_records(records):
        distinct = {
            point["timestamp"]: point for point in records
            if datetime.fromtimestamp(point["timestamp"], SHANGHAI).date() == latest_date
        }
        return sorted(distinct.values(), key=lambda point: point["timestamp"])

    points = latest_records(points)
    auction_points = latest_records(auction_points)
    preopen_result_points = latest_records(preopen_result_points)
    return {
        "secid": secid,
        "points": points,
        "auction_points": auction_points,
        "preopen_result_points": preopen_result_points,
        "trading_date": latest_date.isoformat() if latest_date else None,
        "previous_close": finite_number(data.get("preClose")),
        "source_timestamp": points[-1]["timestamp"] if points else None,
        "auction_source_timestamp": auction_points[-1]["timestamp"] if auction_points else None,
        "preopen_result_source_timestamp": preopen_result_points[-1]["timestamp"] if preopen_result_points else None,
        "chart_type": "regular_session",
        "volume_unit": "源单位，未转换为股或手",
        "auction_data_version": 1,
        "auction_verified": False,
        "source": "东方财富公开网页分时",
    }


def get_trends(secid):
    moment = datetime.now(SHANGHAI)
    clock_minutes = moment.hour * 60 + moment.minute
    ttl = 5 if moment.weekday() < 5 and 555 <= clock_minutes <= 570 else 30
    value, metadata = cached(("trends", secid, ttl), ttl, lambda: load_trends(secid))
    return {**value, **metadata, "refresh_after_seconds": ttl}
