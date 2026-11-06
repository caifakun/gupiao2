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


FLOW_FIELDS = (
    ("main", "主力（超大单＋大单）", "f62", "f184", None, None),
    ("super_large", "超大单", "f66", "f69", "f64", "f65"),
    ("large", "大单", "f72", "f75", "f70", "f71"),
    ("medium", "中单", "f78", "f81", "f76", "f77"),
    ("small", "小单", "f84", "f87", "f82", "f83"),
)


def load_current_flow(secid):
    fields = "f12,f13,f14,f3,f124,f62,f184,f66,f69,f72,f75,f78,f81,f84,f87,f64,f65,f70,f71,f76,f77,f82,f83"
    data = eastmoney_data("https://push2.eastmoney.com/api/qt/ulist.np/get", {
        "secids": secid, "fltt": "2", "fields": fields,
        "ut": "b2884a393a59ad64002292a3e90d46a5",
    })
    records = data.get("diff")
    if isinstance(records, dict):
        records = list(records.values())
    if not isinstance(records, list) or len(records) != 1 or not isinstance(records[0], dict):
        raise DataError("数据源未返回该股票的资金分类")
    record = records[0]
    market, code = secid.split(".", 1)
    if str(record.get("f12")) != code or str(record.get("f13")) != market:
        raise DataError("资金数据的证券代码或市场不匹配")
    rows = [{
        "id": key, "label": label,
        "net": finite_number(record.get(net_field)),
        "ratio": finite_number(record.get(ratio_field)),
        "inflow": finite_number(record.get(in_field)) if in_field else None,
        "outflow": finite_number(record.get(out_field)) if out_field else None,
    } for key, label, net_field, ratio_field, in_field, out_field in FLOW_FIELDS]
    for field in ("inflow", "outflow"):
        values = [rows[index][field] for index in (1, 2)]
        rows[0][field] = finite_number(sum(values)) if all(value is not None for value in values) else None
    return {
        "secid": secid, "name": str(record.get("f14") or code), "rows": rows,
        "change_pct": finite_number(record.get("f3")),
        "source_timestamp": source_timestamp(record.get("f124")),
        "timestamp_basis": "源行情时间，非逐笔资金更新时间",
        "unit": "CNY", "source": "东方财富公开网页资金流向",
    }


def load_flow_history(secid):
    data = eastmoney_data("https://push2his.eastmoney.com/api/qt/stock/fflow/daykline/get", {
        "secid": secid, "lmt": "60", "klt": "101", "fields1": "f1,f2,f3,f7",
        "fields2": "f51,f52,f53,f54,f55,f56,f57,f58,f59,f60,f61,f62,f63",
        "ut": "b2884a393a59ad64002292a3e90d46a5",
    })
    if str(data.get("code")) != secid.split(".", 1)[1]:
        raise DataError("历史资金数据的证券代码不匹配")
    records = data.get("klines")
    if not isinstance(records, list):
        raise DataError("数据源未返回历史资金记录")
    today = datetime.now(SHANGHAI).date()
    dated = {}
    for record in records:
        fields = record.split(",") if isinstance(record, str) else []
        if len(fields) < 13:
            continue
        try:
            date = datetime.strptime(fields[0], "%Y-%m-%d").date()
        except ValueError:
            continue
        if date >= today:
            continue
        dated[date.isoformat()] = {
            "date": date.isoformat(), "main": finite_number(fields[1]),
            "small": finite_number(fields[2]), "medium": finite_number(fields[3]),
            "large": finite_number(fields[4]), "super_large": finite_number(fields[5]),
            "close": finite_number(fields[11]), "change_pct": finite_number(fields[12]),
        }
    rows = [dated[date] for date in sorted(dated)]
    summaries = []
    for window in (5, 10, 20):
        selected = rows[-window:]
        values = [row["main"] for row in selected if row["main"] is not None]
        complete = len(selected) == window and len(values) == window
        summaries.append({
            "window": window, "sample_count": len(selected), "valid_count": len(values),
            "complete": complete, "net": finite_number(sum(values)) if complete else None,
            "start_date": selected[0]["date"] if selected else None,
            "end_date": selected[-1]["date"] if selected else None,
        })
    return {
        "secid": secid, "rows": rows[-20:], "summaries": summaries,
        "source_date": rows[-1]["date"] if rows else None, "source_timestamp": None,
        "unit": "CNY", "excludes_today": True, "source": "东方财富公开网页资金日线",
    }


def get_money_flow(secid):
    result = {"secid": secid, "current": None, "history": None, "errors": []}
    for part, ttl, loader in (("current", 30, load_current_flow), ("history", 300, load_flow_history)):
        try:
            value, metadata = cached(("money-flow", part, secid), ttl, lambda: loader(secid))
            result[part] = {**value, **metadata}
        except DataError as error:
            result["errors"].append({"part": part, "message": str(error)})
    return result


def datacenter_rows(report, filters, sort_column="TRADE_DATE", latest_only=False):
    payload = request_json("https://datacenter-web.eastmoney.com/api/data/v1/get", {
        "reportName": report, "columns": "ALL", "filter": filters,
        "pageNumber": "1", "pageSize": "1" if latest_only else "100", "sortTypes": "-1",
        "sortColumns": sort_column, "source": "WEB", "client": "WEB",
    }, "eastmoney")
    if payload.get("code") == 9201 and payload.get("result") is None and payload.get("message") == "返回数据为空":
        return []
    if payload.get("success") is not True:
        raise DataError("东方财富未返回有效龙虎榜数据")
    result = payload.get("result")
    if result is None:
        return []
    if not isinstance(result, dict) or not isinstance(result.get("data"), list):
        raise DataError("龙虎榜数据结构异常")
    count = finite_number(result.get("count"))
    pages = finite_number(result.get("pages"))
    if not latest_only and ((count is not None and count > 100) or (pages is not None and pages > 1)):
        raise DataError("龙虎榜记录超过本次安全上限，未展示不完整数据")
    return [row for row in result["data"] if isinstance(row, dict)]
