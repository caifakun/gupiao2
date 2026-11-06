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


def parse_volume_ratio(data):
    raw = finite_number(data.get("f50"))
    precision = data.get("f152")
    if raw is None or raw < 0:
        return None
    if type(precision) is not int or not 0 <= precision <= 6:
        return None
    return raw / (10 ** precision)


def load_quote(secid):
    data = eastmoney_data(
        "https://push2.eastmoney.com/api/qt/stock/get",
        {
            "secid": secid,
            "invt": "2",
            "fltt": "1",
            "ut": "fa5fd1943c7b386f172d6893dbfba10b",
            "fields": "f43,f44,f45,f46,f47,f48,f57,f58,f59,f60,f86,f19,f20,f39,f40,f50,f152,f168,f171,f127",
        },
    )
    precision = data.get("f59")
    if type(precision) is not int or not 0 <= precision <= 6:
        raise DataError("报价精度异常，未转换或展示价格")
    if str(data.get("f57")) != secid.split(".", 1)[1]:
        raise DataError("数据源返回的证券代码不匹配")

    def price(field):
        value = finite_number(data.get(field))
        return value / (10 ** precision) if value is not None and value > 0 else None

    def nonnegative(field, precision_field=None):
        value = finite_number(data.get(field))
        if value is None or value < 0:
            return None
        if precision_field is None:
            return value
        decimal_places = data.get(precision_field)
        if type(decimal_places) is not int or not 0 <= decimal_places <= 6:
            return None
        return value / (10 ** decimal_places)

    latest = price("f43")
    previous = price("f60")
    industry = data.get("f127")
    industry = industry.strip() if isinstance(industry, str) else ""
    return {
        "secid": secid,
        "name": str(data.get("f58") or ""),
        "industry": industry if industry and industry != "-" else None,
        "precision": precision,
        "latest_price": latest,
        "previous_close": previous,
        "change_pct": (latest / previous - 1) * 100 if latest and previous else None,
        "volume_ratio": parse_volume_ratio(data),
        "open_price": price("f46"),
        "high_price": price("f44"),
        "low_price": price("f45"),
        "volume_lots": nonnegative("f47"),
        "turnover_amount": nonnegative("f48"),
        "turnover_rate": nonnegative("f168", "f152"),
        "amplitude_pct": nonnegative("f171", "f152"),
        "source_timestamp": source_timestamp(data.get("f86")),
        "best_bid_price": price("f19"),
        "best_ask_price": price("f39"),
        "best_bid_size_raw": finite_number(data.get("f20")),
        "best_ask_size_raw": finite_number(data.get("f40")),
        "auction_verified": False,
        "auction_reference_price": None,
        "auction_matched_volume": None,
        "auction_unmatched_volume": None,
        "auction_unmatched_side": None,
        "source": "东方财富公开网页行情",
    }


def quote_item(secid):
    try:
        quote, metadata = cached(("quote", secid), 1, lambda: load_quote(secid))
        return {"quote": {**quote, **metadata}}
    except DataError as error:
        return {"error": {"secid": secid, "message": str(error)}}


def get_quotes(secids):
    results = list(QUOTE_POOL.map(quote_item, secids))
    return {
        "data": [item["quote"] for item in results if "quote" in item],
        "errors": [item["error"] for item in results if "error" in item],
        "auction_verified": False,
        "received_at": time.time(),
    }


def load_watchlist_snapshot(secids):
    if not WATCHLIST_LIMIT.acquire(timeout=2):
        raise DataError("全自选快照采集繁忙，请稍后重试")
    try:
        data = eastmoney_data("https://push2.eastmoney.com/api/qt/ulist.np/get", {
            "secids": ",".join(secids), "fltt": "2",
            "fields": "f2,f3,f12,f13,f14,f100,f124",
            "ut": "b2884a393a59ad64002292a3e90d46a5",
        })
    finally:
        WATCHLIST_LIMIT.release()
    records = data.get("diff")
    if isinstance(records, dict):
        records = list(records.values())
    if not isinstance(records, list):
        raise DataError("数据源未返回有效的全自选快照")
    requested = set(secids)
    parsed = {}
    duplicates = set()
    for record in records:
        if not isinstance(record, dict):
            continue
        secid = f"{record.get('f13')}.{record.get('f12')}"
        if secid not in requested:
            continue
        if secid in parsed:
            duplicates.add(secid)
            continue
        industry = record.get("f100")
        industry = industry.strip() if isinstance(industry, str) else ""
        latest = finite_number(record.get("f2"))
        parsed[secid] = {
            "secid": secid,
            "name": str(record.get("f14") or "")[:40],
            "latest_price": latest if latest is not None and latest > 0 else None,
            "change_pct": finite_number(record.get("f3")),
            "industry": industry if industry and industry != "-" and len(industry) <= 80 else None,
            "source_timestamp": source_timestamp(record.get("f124")),
            "source": "东方财富公开网页批量快照",
        }
    return {
        "data": [parsed[secid] for secid in secids if secid in parsed and secid not in duplicates],
        "errors": [{"secid": secid, "message": "源返回重复快照" if secid in duplicates else "本轮未返回该股票快照"}
                   for secid in secids if secid not in parsed or secid in duplicates],
    }


def get_watchlist_snapshot(secids):
    value, metadata = cached(("watchlist", tuple(secids)), 4, lambda: load_watchlist_snapshot(secids))
    return {
        "data": [{**record, **metadata} for record in value["data"]],
        "errors": value["errors"],
        "received_at": time.time(),
    }
