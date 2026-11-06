import json
import math
import re
import threading
import time
from collections import defaultdict
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from datetime import datetime, timedelta

from ..core.cache import cached
from ..core.numbers import DataError, finite_number, source_timestamp, validate_secid
from ..core.runtime import (
    ROOT, SHANGHAI, QUOTE_POOL, WATCHLIST_LIMIT,
    DARK_FLOW_LOCK, DARK_FLOW_STOP, DARK_FLOW_STATE,
)
from ..providers.eastmoney import eastmoney_data
from ..providers.http import request_json


def parse_darktrade_row(row):
    market, code = row.get("3"), row.get("4")
    if type(market) is not int or market not in (0, 1):
        return None
    if not isinstance(code, str) or len(code) != 6 or not code.isascii() or not code.isdigit():
        return None
    activity = finite_number(row.get("11"))
    return {
        "secid": f"{market}.{code}",
        "lit_net": finite_number(row.get("7")),
        "dark_net": finite_number(row.get("6")),
        "main_net": finite_number(row.get("8")),
        "activity_pct": finite_number(activity * 100) if activity is not None and activity >= 0 else None,
    }


def darktrade_timestamp(day, value):
    if type(value) not in (int, str):
        return None
    clock = str(value).zfill(6)
    if not re.fullmatch(r"[0-9]{6}", clock):
        return None
    try:
        moment = datetime.strptime(day + clock, "%Y-%m-%d%H%M%S").replace(tzinfo=SHANGHAI)
    except ValueError:
        return None
    return source_timestamp(moment.timestamp())


def load_darktrade_page(day, page, deadline):
    if DARK_FLOW_STOP.is_set() or time.monotonic() >= deadline:
        raise DataError("当日榜单采集已停止或超时")
    if datetime.now(SHANGHAI).date().isoformat() != day:
        raise DataError("北京时间已跨日，丢弃上一日的榜单采集")
    payload = request_json("https://quotederivates.eastmoney.com/datacenter/darktrade", {
        "version": 100, "cver": 100, "date": day.replace("-", ""),
        "StartPage": page, "NumPerPage": 100, "sortflag": 6, "desc": 1,
        "market": "", "datetype": "",
    }, "eastmoney-darktrade")
    if type(payload.get("errid")) is not int or payload["errid"] != 0:
        raise DataError("东方财富当日明暗盘榜单暂不可用，不尝试绕过权限")
    if str(payload.get("1")) != day.replace("-", ""):
        raise DataError("榜单未返回北京时间当日数据，不展示历史值")
    total, records = payload.get("2"), payload.get("data")
    if type(total) is not int or not 0 <= total <= 100000:
        raise DataError("榜单覆盖数量异常")
    if not isinstance(records, list) or len(records) > 100 or any(not isinstance(row, dict) for row in records):
        raise DataError("榜单分页结构异常")
    fetched_at = time.time()
    rows = []
    for raw in records:
        row = parse_darktrade_row(raw)
        if row is not None:
            rows.append({
                **row, "source_date": day,
                "source_timestamp": darktrade_timestamp(day, raw.get("5")),
                "fetched_at": fetched_at,
            })
    return rows, total, len(rows) != len(records) or len(records) != max(0, min(100, total - (page - 1) * 100))


def collect_darktrade(day, job):
    deadline = time.monotonic() + 60
    seen = set()
    errors = []

    def publish(rows, total, partial):
        with DARK_FLOW_LOCK:
            if DARK_FLOW_STATE.get("job") is not job or DARK_FLOW_STOP.is_set():
                return False
            if datetime.now(SHANGHAI).date().isoformat() != day:
                return False
            current = DARK_FLOW_STATE
            if current["total"] is not None and current["total"] != total:
                partial = True
            if current["total"] is None:
                current["total"] = total
                current["pages_total"] = max(1, math.ceil(total / 100))
            current["pages_loaded"] += 1
            for row in rows:
                secid = row["secid"]
                if secid in seen:
                    partial = True
                seen.add(secid)
                existing = current["records"].get(secid)
                if existing and existing["source_timestamp"] is not None:
                    if row["source_timestamp"] is None or row["source_timestamp"] < existing["source_timestamp"]:
                        continue
                if existing is None and len(current["records"]) >= 10000:
                    partial = True
                    continue
                current["records"][secid] = row
            current["partial"] = current["partial"] or partial
            current["matched_count"] = len(seen)
            return True

    try:
        rows, total, partial = load_darktrade_page(day, 1, deadline)
        if not publish(rows, total, partial):
            return
        pages = max(1, math.ceil(total / 100))
        if pages > 100:
            errors.append("源榜单超过本轮100页采集上限，覆盖不完整")
        with ThreadPoolExecutor(max_workers=2, thread_name_prefix="market-darktrade") as pool:
            pending = {}
            next_page = 2
            failures = 0
            while next_page <= min(pages, 100) or pending:
                with DARK_FLOW_LOCK:
                    active = DARK_FLOW_STATE.get("job") is job
                if not active or DARK_FLOW_STOP.is_set() or datetime.now(SHANGHAI).date().isoformat() != day:
                    break
                remaining = deadline - time.monotonic()
                if remaining <= 0 or failures >= 3:
                    errors.append("本轮采集超时或部分分页失败，覆盖不完整")
                    break
                while next_page <= min(pages, 100) and len(pending) < 2:
                    pending[pool.submit(load_darktrade_page, day, next_page, deadline)] = next_page
                    next_page += 1
                completed, unused = wait(pending, timeout=remaining, return_when=FIRST_COMPLETED)
                for future in completed:
                    pending.pop(future)
                    try:
                        rows, page_total, partial = future.result()
                        if not publish(rows, page_total, partial):
                            return
                    except DataError as error:
                        failures += 1
                        errors.append(str(error))
            for future in pending:
                future.cancel()
    except DataError as error:
        errors.append(str(error))
    except Exception:
        errors.append("当日明暗盘榜单采集失败，未取得完整新快照")
    finally:
        with DARK_FLOW_LOCK:
            if DARK_FLOW_STATE.get("job") is job:
                current = DARK_FLOW_STATE
                complete = current["pages_total"] is not None and current["pages_loaded"] == current["pages_total"]
                if not complete and not errors:
                    errors.append("本轮榜单采集未完成")
                current["updating"] = False
                current["partial"] = current["partial"] or not complete or bool(errors)
                current["error"] = "；".join(dict.fromkeys(errors)) or None
                current["retry_at"] = time.monotonic() + (60 if errors else 300)


def get_dark_flow(secid):
    day = datetime.now(SHANGHAI).date().isoformat()
    with DARK_FLOW_LOCK:
        current = DARK_FLOW_STATE
        if current.get("source_date") != day:
            current.clear()
            current.update({
                "source_date": day, "records": {}, "updating": False,
                "pages_loaded": 0, "pages_total": None, "total": None,
                "matched_count": 0, "partial": False, "error": None,
                "retry_at": 0, "started_at": 0,
            })
        if not current["updating"] and time.monotonic() >= current["retry_at"] and not DARK_FLOW_STOP.is_set():
            job = object()
            current.update({
                "job": job, "updating": True, "pages_loaded": 0,
                "pages_total": None, "total": None, "matched_count": 0,
                "partial": False, "error": None, "started_at": time.time(),
            })
            threading.Thread(target=collect_darktrade, args=(day, job), daemon=True, name="market-darktrade-scan").start()
        snapshot = current["records"].get(secid)
        stale = snapshot is not None and (snapshot["fetched_at"] < current["started_at"] or time.time() - snapshot["fetched_at"] > 300)
        status = "updating" if current["updating"] else "ready" if snapshot else "error" if current["error"] else "not_found"
        return {
            "secid": secid, "source_date": day, "snapshot": snapshot,
            "status": status, "updating": current["updating"], "stale": stale,
            "partial": current["partial"], "error": current["error"],
            "pages_loaded": current["pages_loaded"], "pages_total": current["pages_total"],
            "reported_count": current["total"], "matched_count": current["matched_count"],
            "poll_after_seconds": 3 if current["updating"] else max(1, math.ceil(current["retry_at"] - time.monotonic())),
            "unit": "CNY", "source": "东方财富当日暗盘资金榜（模型测算）",
            "timestamp_basis": "源榜单记录时间，非逐笔资金时间；分页不是同一时刻快照",
        }
