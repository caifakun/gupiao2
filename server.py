import argparse
import json
import math
import os
import re
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from collections import defaultdict
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from datetime import datetime, timedelta, timezone
from http.client import HTTPException
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path


ROOT = Path(__file__).resolve().parent
SHANGHAI = timezone(timedelta(hours=8))
QUOTE_POOL = ThreadPoolExecutor(max_workers=4, thread_name_prefix="market-quote")
UPSTREAM_LIMIT = threading.BoundedSemaphore(4)
WATCHLIST_LIMIT = threading.BoundedSemaphore(1)
CACHE_GUARD = threading.Lock()
CACHE_LOCKS = tuple(threading.Lock() for index in range(32))
CACHE = {}
MAX_BODY = 10 * 1024 * 1024
SECID_PATTERN = re.compile(r"[01]\.[0-9]{6}\Z")
DARK_FLOW_LOCK = threading.Lock()
DARK_FLOW_STOP = threading.Event()
DARK_FLOW_STATE = {}


class DataError(Exception):
    pass


def finite_number(value):
    if value is None or isinstance(value, bool):
        return None
    try:
        result = float(str(value).strip().replace(",", "").removesuffix("%"))
        return result if math.isfinite(result) else None
    except (TypeError, ValueError):
        return None


def source_timestamp(value):
    timestamp = finite_number(value)
    if timestamp is None or timestamp < 946684800 or timestamp > time.time() + 300:
        return None
    return int(timestamp)


def validate_secid(secid):
    if not SECID_PATTERN.fullmatch(secid):
        raise ValueError("证券代码格式须为1.六位沪市代码或0.六位深市代码")
    return secid


def request_json(base_url, parameters, source):
    proxy = os.environ.get("MARKET_PROXY", "").strip()
    if proxy:
        try:
            parsed = urllib.parse.urlsplit(proxy)
            if parsed.scheme not in ("http", "https") or not parsed.hostname:
                raise ValueError
            parsed.port
        except ValueError:
            raise DataError("MARKET_PROXY须为有效的HTTP或HTTPS代理地址") from None
    opener = urllib.request.build_opener(
        urllib.request.ProxyHandler({"http": proxy, "https": proxy} if proxy else {})
    )
    request = urllib.request.Request(
        base_url + "?" + urllib.parse.urlencode(parameters),
        headers={
            "User-Agent": "Mozilla/5.0",
            "Accept": "application/json,text/plain,*/*",
            "Referer": {
                "nasdaq": "https://www.nasdaq.com/",
                "eastmoney-darktrade": "https://emrnweb.eastmoney.com/graymarket/",
            }.get(source, "https://quote.eastmoney.com/"),
        },
    )
    if not UPSTREAM_LIMIT.acquire(timeout=10):
        raise DataError("上游采集繁忙，请稍后重试")
    try:
        with opener.open(request, timeout=8) as response:
            body = response.read(MAX_BODY + 1)
        if len(body) > MAX_BODY:
            raise DataError("数据源响应超出安全大小限制")
        try:
            text = body.decode("utf-8-sig")
        except UnicodeDecodeError:
            if source != "eastmoney-darktrade":
                raise
            text = body.decode("gb18030")
        payload = json.loads(text)
        if not isinstance(payload, dict):
            raise DataError("数据源响应结构异常")
        return payload
    except urllib.error.HTTPError as error:
        raise DataError(f"数据源返回HTTP {error.code}，未取得新行情") from None
    except (urllib.error.URLError, TimeoutError, OSError, HTTPException):
        raise DataError("无法连接数据源或请求超时；请检查网络及MARKET_PROXY配置") from None
    except (ValueError, UnicodeError):
        raise DataError("数据源未返回有效JSON") from None
    finally:
        UPSTREAM_LIMIT.release()


def cached(key, ttl, loader):
    with CACHE_LOCKS[hash(key) % len(CACHE_LOCKS)]:
        with CACHE_GUARD:
            entry = CACHE.get(key)
            if entry and time.monotonic() < entry[0]:
                return entry[1], {"cached": True, "fetched_at": entry[2]}
        value = loader()
        acquired = time.time()
        with CACHE_GUARD:
            if len(CACHE) >= 256 and key not in CACHE:
                oldest = min(CACHE, key=lambda item: CACHE[item][0])
                CACHE.pop(oldest)
            CACHE[key] = (time.monotonic() + ttl, value, acquired)
        return value, {"cached": False, "fetched_at": acquired}


def eastmoney_data(url, parameters):
    payload = request_json(url, parameters, "eastmoney")
    data = payload.get("data")
    if payload.get("rc") != 0 or not isinstance(data, dict):
        raise DataError("东方财富未返回有效数据，证券可能不存在或接口暂不可用")
    return data


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


class MarketHandler(BaseHTTPRequestHandler):
    def send_body(self, status, body, content_type, head=False):
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header(
            "Content-Security-Policy",
            "default-src 'self'; script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline'; "
            "img-src 'self' data:; connect-src 'self'; base-uri 'none'; form-action 'none'; frame-ancestors 'none'",
        )
        self.end_headers()
        if not head:
            self.wfile.write(body)

    def send_json(self, status, payload, head=False):
        body = json.dumps(payload, ensure_ascii=False, allow_nan=False, separators=(",", ":")).encode("utf-8")
        self.send_body(status, body, "application/json; charset=utf-8", head)

    def local_request(self):
        port = self.server.server_port
        hosts = {f"127.0.0.1:{port}", f"localhost:{port}"}
        if self.headers.get("Host", "").lower() not in hosts:
            return False
        origin = self.headers.get("Origin")
        return not origin or origin.lower() in {f"http://{host}" for host in hosts}

    def route(self, head=False):
        try:
            if not self.local_request():
                self.send_json(403, {"error": "服务仅允许本机同源访问"}, head)
                return
            parsed = urllib.parse.urlsplit(self.path)
            path = parsed.path
            query = urllib.parse.parse_qs(parsed.query, keep_blank_values=True, max_num_fields=12)
            if path.startswith("/api/") and self.headers.get("Sec-Fetch-Site") == "cross-site":
                self.send_json(403, {"error": "不允许跨站点调用本地行情接口"}, head)
                return
            if path == "/api/health":
                self.send_json(200, {
                    "status": "ok", "server_time": time.time(), "auction_verified": False,
                    "proxy_configured": bool(os.environ.get("MARKET_PROXY", "").strip()),
                    "note": "健康检查不表示上游行情可用，也不表示行情实时。",
                }, head)
                return
            static = {"/": ("index.html", "text/html; charset=utf-8"),
                      "/index.html": ("index.html", "text/html; charset=utf-8"),
                      "/market-data.js": ("market-data.js", "text/javascript; charset=utf-8")}
            if path in static:
                filename, content_type = static[path]
                self.send_body(200, (ROOT / filename).read_bytes(), content_type, head)
                return
            if head:
                self.send_json(405, {"error": "此接口只支持GET"}, True)
                return

            def argument(name, default):
                values = query.get(name, [default])
                if len(values) != 1:
                    raise ValueError("参数不能重复")
                return values[0]

            if path == "/api/quotes":
                identifiers = list(dict.fromkeys(argument("secids", "").split(",")))
                if not 1 <= len(identifiers) <= 9:
                    raise ValueError("每次支持1至9只股票")
                for secid in identifiers:
                    validate_secid(secid)
                result = get_quotes(identifiers)
                self.send_json(200 if result["data"] else 502, result)
            elif path == "/api/watchlist-snapshot":
                identifiers = list(dict.fromkeys(argument("secids", "").split(",")))
                if not 1 <= len(identifiers) <= 50:
                    raise ValueError("全自选快照每次支持1至50只股票")
                for secid in identifiers:
                    validate_secid(secid)
                result = get_watchlist_snapshot(identifiers)
                self.send_json(200 if result["data"] else 502, result)
            elif path == "/api/trends":
                self.send_json(200, get_trends(validate_secid(argument("secid", ""))))
            elif path == "/api/money-flow":
                result = get_money_flow(validate_secid(argument("secid", "")))
                self.send_json(200 if result["current"] is not None or result["history"] is not None else 502, result)
            elif path == "/api/dark-flow":
                self.send_json(200, get_dark_flow(validate_secid(argument("secid", ""))))
            elif path == "/api/billboard":
                self.send_json(200, get_billboard(validate_secid(argument("secid", ""))))
            elif path == "/api/sectors":
                market = argument("market", "CN")
                kind = argument("kind", "industry")
                page_string = argument("page", "1")
                if market not in ("CN", "US") or kind not in ("industry", "concept"):
                    raise ValueError("市场或板块分类无效")
                if not re.fullmatch(r"[0-9]{1,4}", page_string) or not 1 <= int(page_string) <= 1000:
                    raise ValueError("页码须在1至1000之间")
                self.send_json(200, get_sectors(market, kind, int(page_string)))
            else:
                self.send_json(404, {"error": "接口或文件不存在"})
        except ValueError as error:
            self.send_json(400, {"error": str(error)}, head)
        except DataError as error:
            self.send_json(502, {"error": str(error)}, head)
        except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
            return
        except Exception:
            self.send_json(500, {"error": "本地服务处理失败，未取得新数据"}, head)

    def do_GET(self):
        self.route()

    def do_HEAD(self):
        self.route(head=True)


def main():
    parser = argparse.ArgumentParser(description="竞观本地行情服务")
    parser.add_argument("--port", type=int, default=8000)
    arguments = parser.parse_args()
    if not 1 <= arguments.port <= 65535:
        parser.error("端口必须在1至65535之间")
    try:
        server = ThreadingHTTPServer(("127.0.0.1", arguments.port), MarketHandler)
    except OSError as error:
        parser.exit(1, f"无法启动服务，端口可能被占用：{error}\n")
    print(f"竞观已启动：http://127.0.0.1:{arguments.port}", flush=True)
    print("仅监听本机。按 Ctrl+C 停止；公开行情不保证实时，竞价字段尚未验证。", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        DARK_FLOW_STOP.set()
        server.server_close()
        QUOTE_POOL.shutdown(wait=False, cancel_futures=True)


if __name__ == "__main__":
    main()
