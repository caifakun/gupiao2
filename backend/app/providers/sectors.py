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


def load_china_sectors(kind, page):
    data = eastmoney_data(
        "https://push2.eastmoney.com/api/qt/clist/get",
        {
            "pn": page, "pz": 50, "po": 1, "np": 1, "fltt": 2, "invt": 2,
            "fid": "f3", "fs": f"m:90 t:{2 if kind == 'industry' else 3} f:!50",
            "fields": "f2,f3,f6,f12,f14,f104,f105,f124,f128,f140,f141",
        },
    )
    records = data.get("diff")
    if isinstance(records, dict):
        records = list(records.values())
    if not isinstance(records, list):
        raise DataError("板块列表结构异常")
    rows = []
    for item in records:
        if not isinstance(item, dict) or not item.get("f12"):
            continue
        rows.append({
            "code": str(item["f12"]),
            "name": str(item.get("f14") or item["f12"]),
            "change_pct": finite_number(item.get("f3")),
            "turnover": finite_number(item.get("f6")),
            "leader": str(item.get("f128") or "—"),
            "source_timestamp": source_timestamp(item.get("f124")),
        })
    timestamps = [item["source_timestamp"] for item in rows if item["source_timestamp"]]
    total = finite_number(data.get("total"))
    if total is None or total < 0:
        raise DataError("板块总数无效")
    return {
        "market": "CN", "kind": kind, "rows": rows, "page": page,
        "page_size": 50, "total": int(total),
        "source_timestamp": min(timestamps) if timestamps else None,
        "missing_source_times": len(rows) - len(timestamps),
        "source": "东方财富行业板块" if kind == "industry" else "东方财富概念板块",
        "methodology": "涨跌幅及成交额使用数据源原值；统计卡片仅覆盖当前页。",
    }


def load_us_sectors():
    payload = request_json(
        "https://api.nasdaq.com/api/screener/stocks",
        {"tableonly": "true", "limit": 25, "download": "true"},
        "nasdaq",
    )
    data = payload.get("data")
    status = payload.get("status") or {}
    if not isinstance(data, dict) or status.get("rCode", 200) != 200:
        raise DataError("Nasdaq未返回可用筛选器数据")
    records = data.get("rows")
    if not isinstance(records, list) or not records:
        raise DataError("Nasdaq行业样本为空或响应结构变化")
    groups = defaultdict(list)
    seen = set()
    classified = 0
    for item in records:
        if not isinstance(item, dict):
            continue
        symbol = str(item.get("symbol") or "").strip()
        if not symbol or symbol in seen:
            continue
        seen.add(symbol)
        sector = str(item.get("sector") or "").strip()
        if not sector or sector in ("N/A", "n/a", "—"):
            continue
        classified += 1
        change = finite_number(item.get("pctchange"))
        if change is not None:
            groups[sector].append({"symbol": symbol, "change_pct": change})
    rows = []
    for sector, members in groups.items():
        leader = max(members, key=lambda item: item["change_pct"])
        rows.append({
            "name": sector,
            "change_pct": sum(item["change_pct"] / len(members) for item in members),
            "sample_count": len(members),
            "leader": leader["symbol"],
            "leader_change_pct": leader["change_pct"],
        })
    rows.sort(key=lambda item: item["change_pct"], reverse=True)
    if not rows:
        raise DataError("Nasdaq没有可计算涨跌幅的有效行业样本")
    return {
        "market": "US", "rows": rows, "page": 1, "page_size": len(rows), "total": len(rows),
        "source_timestamp": None,
        "source_as_of": data.get("asOf"),
        "freshness": "unverified",
        "total_samples": len(seen), "classified_samples": classified,
        "valid_samples": sum(len(members) for members in groups.values()),
        "source": "Nasdaq股票筛选器",
        "methodology": "按Nasdaq原始sector分类，对有有效pctchange的去重样本取算术平均；非官方行业指数，不保证实时。",
    }


def get_sectors(market, kind, page):
    if market == "US":
        value, metadata = cached(("us-sectors",), 600, load_us_sectors)
    else:
        value, metadata = cached(("cn-sectors", kind, page), 30, lambda: load_china_sectors(kind, page))
    return {**value, **metadata}
