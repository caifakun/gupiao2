import json
import urllib.parse
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


from .funds import datacenter_rows

def read_seat_associations():
    path = ROOT / "seat-labels.json"
    try:
        config = json.loads(path.read_text(encoding="utf-8"))
        entries = config.get("associations") if isinstance(config, dict) else None
        if not isinstance(entries, list) or len(entries) > 500:
            raise ValueError
        valid = []
        for entry in entries:
            if not isinstance(entry, dict):
                raise ValueError
            for field in ("department_code", "department_name", "alias", "evidence_url", "evidence_date", "valid_from", "valid_to"):
                if not isinstance(entry.get(field), str) or not entry[field].strip():
                    raise ValueError
            url = urllib.parse.urlsplit(entry["evidence_url"])
            if url.scheme != "https" or not url.hostname or url.username or url.password:
                raise ValueError
            evidence_date = datetime.strptime(entry["evidence_date"], "%Y-%m-%d").date()
            start = datetime.strptime(entry["valid_from"], "%Y-%m-%d").date()
            end = datetime.strptime(entry["valid_to"], "%Y-%m-%d").date()
            if start > end or evidence_date > datetime.now(SHANGHAI).date():
                raise ValueError
            valid.append({field: entry[field].strip() for field in (
                "department_code", "department_name", "alias", "evidence_url", "evidence_date", "valid_from", "valid_to",
            )})
        return valid, None
    except FileNotFoundError:
        return [], "暂无已核验的游资席位关联配置，不展示推测身份"
    except (OSError, ValueError, TypeError):
        return [], "游资关联配置无效，已停用关联标签；原始席位仍正常展示"


def seat_tags(row, trade_date, associations):
    name = str(row.get("OPERATEDEPT_NAME") or "")
    code = str(row.get("OPERATEDEPT_CODE") or "")
    category = "机构专用" if name == "机构专用" else "交易通道" if name in ("沪股通专用", "深股通专用") else "营业部席位"
    matches = [entry for entry in associations if entry["department_code"] == code
               and entry["department_name"] == name and entry["valid_from"] <= trade_date <= entry["valid_to"]]
    return category, matches


def get_billboard(secid):
    today = datetime.now(SHANGHAI).date()
    start = (today - timedelta(days=90)).isoformat()
    code = secid.split(".", 1)[1]
    filters = f'(SECURITY_CODE="{code}")(TRADE_DATE>=\'{start}\')(TRADE_DATE<=\'{today.isoformat()}\')'
    listing, metadata = cached(("billboard-dates", secid, today.isoformat()), 600, lambda: datacenter_rows(
        "RPT_DAILYBILLBOARD_DETAILS", filters, latest_only=True))
    valid = []
    for row in listing:
        date_text = str(row.get("TRADE_DATE") or "")[:10]
        try:
            date = datetime.strptime(date_text, "%Y-%m-%d").date()
        except ValueError:
            continue
        if str(row.get("SECURITY_CODE")) == code and start <= date.isoformat() <= today.isoformat():
            valid.append(row)
    associations, label_warning = read_seat_associations()
    result = {
        "secid": secid, "lookback_days": 90, "start_date": start, "trade_date": None,
        "groups": [], "errors": [], "label_warning": label_warning,
        "association_count": len(associations), "source_timestamp": None,
        "source": "东方财富公开网页龙虎榜（非盘中全市场资金）", **metadata,
    }
    if not valid:
        return result
    trade_date = max(str(row["TRADE_DATE"])[:10] for row in valid)
    result["trade_date"] = trade_date
    listing, reasons_metadata = cached(("billboard-reasons", secid, trade_date), 600, lambda: datacenter_rows(
        "RPT_DAILYBILLBOARD_DETAILS", f'(SECURITY_CODE="{code}")(TRADE_DATE=\'{trade_date}\')'))
    groups = {}
    for row in listing:
        if str(row.get("SECURITY_CODE")) == code and str(row.get("TRADE_DATE") or "")[:10] == trade_date:
            reason_code = str(row.get("CHANGE_TYPE") or row.get("EXPLANATION") or "未提供上榜原因")
            groups[reason_code] = {"reason_code": reason_code, "reason": str(row.get("EXPLANATION") or "未提供上榜原因"), "rows": []}
    deduplicated = {}
    metadata_items = [metadata, reasons_metadata]
    for side in ("BUY", "SELL"):
        try:
            records, side_metadata = cached(("billboard-seats", secid, trade_date, side), 600, lambda: datacenter_rows(
                "RPT_BILLBOARD_DAILYDETAILS" + side,
                f'(SECURITY_CODE="{code}")(TRADE_DATE=\'{trade_date}\')', side))
            metadata_items.append(side_metadata)
        except DataError as error:
            result["errors"].append({"part": side.lower(), "message": str(error)})
            continue
        for row in records:
            if str(row.get("SECURITY_CODE")) != code or str(row.get("TRADE_DATE") or "")[:10] != trade_date:
                continue
            reason = str(row.get("EXPLANATION") or "未提供上榜原因")
            reason_code = str(row.get("CHANGE_TYPE") or reason)
            group = groups.setdefault(reason_code, {"reason_code": reason_code, "reason": reason, "rows": []})
            department = str(row.get("OPERATEDEPT_NAME") or "未提供席位名称")
            identity = str(row.get("TRADE_ID") or "")
            key = (reason_code, identity, str(row.get("OPERATEDEPT_CODE")), department,
                   row.get("BUY"), row.get("SELL"), row.get("NET"))
            if key not in deduplicated:
                category, tags = seat_tags(row, trade_date, associations)
                normalized = {
                    "department_code": str(row.get("OPERATEDEPT_CODE") or ""), "department_name": department,
                    "buy": finite_number(row.get("BUY")), "sell": finite_number(row.get("SELL")),
                    "net": finite_number(row.get("NET")), "category": category,
                    "associations": tags, "listed_sides": [],
                }
                deduplicated[key] = normalized
                group["rows"].append(normalized)
            if side.lower() not in deduplicated[key]["listed_sides"]:
                deduplicated[key]["listed_sides"].append(side.lower())
    if len(result["errors"]) == 2:
        raise DataError("龙虎榜日期已取得，但买卖席位均获取失败")
    result["groups"] = list(groups.values())
    result["cached"] = all(item["cached"] for item in metadata_items)
    result["fetched_at"] = min(item["fetched_at"] for item in metadata_items)
    return result
