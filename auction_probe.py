import argparse
import json
import time
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime

from server import DataError, ROOT, SHANGHAI, eastmoney_data, source_timestamp, validate_secid


RAW_FIELDS = (
    "f57", "f58", "f59", "f60", "f86", "f292",
    "f19", "f20", "f17", "f18",
    "f39", "f40", "f37", "f38",
    "f43", "f47", "f48",
)
POLL_DELAY = 5


def collect_record(secid):
    started_at = time.time()
    try:
        data = eastmoney_data(
            "https://push2.eastmoney.com/api/qt/stock/get",
            {
                "secid": secid,
                "invt": "2",
                "fltt": "1",
                "ut": "fa5fd1943c7b386f172d6893dbfba10b",
                "fields": ",".join((*RAW_FIELDS, "f531", "f532")),
            },
        )
        if str(data.get("f57")) != secid.split(".", 1)[1]:
            raise DataError("返回的证券代码不匹配")
        return {
            "kind": "snapshot",
            "secid": secid,
            "request_started_at": started_at,
            "fetched_at": time.time(),
            "source_timestamp": source_timestamp(data.get("f86")),
            "raw_fields": data,
            "missing_fields": [field for field in RAW_FIELDS if field not in data],
            "auction_verified": False,
        }
    except DataError as error:
        return {
            "kind": "error",
            "secid": secid,
            "request_started_at": started_at,
            "fetched_at": time.time(),
            "error": str(error),
            "auction_verified": False,
        }


def collect_when_active(secid, deadline):
    if deadline is not None and datetime.now(SHANGHAI) >= deadline:
        return None
    return collect_record(secid)


def write_record(stream, record):
    try:
        encoded = json.dumps(record, ensure_ascii=False, allow_nan=False)
    except (TypeError, ValueError):
        record = {
            "kind": "error",
            "secid": record.get("secid"),
            "request_started_at": record.get("request_started_at"),
            "fetched_at": time.time(),
            "error": "响应包含无法保存为标准JSON的值，未保存该条原始行情",
            "auction_verified": False,
        }
        encoded = json.dumps(record, ensure_ascii=False, allow_nan=False)
    stream.write(encoded + "\n")
    stream.flush()
    return record["kind"]


def run_capture(secids, once, start, end):
    if not once and datetime.now(SHANGHAI) < start:
        print(f"等待北京时间 {start:%Y-%m-%d %H:%M:%S}，按 Ctrl+C 取消。", flush=True)
        while datetime.now(SHANGHAI) < start:
            time.sleep(1)
    if not once and datetime.now(SHANGHAI) >= end:
        print("当天采样窗口已结束，未发起采样。", flush=True)
        return 1

    opened_at = datetime.now(SHANGHAI)
    directory = ROOT / "auction-probe-data" / opened_at.strftime("%Y-%m-%d")
    directory.mkdir(parents=True, exist_ok=True)
    output = directory / f"{opened_at:%H%M%S}-{uuid.uuid4().hex}.jsonl"
    snapshot_count = 0
    error_count = 0
    deadline = None if once else end
    print(f"原始样本文件：{output}", flush=True)
    print("仅核验采样：不转换盘口数量单位，不认定为竞价量，不修改现有图表。", flush=True)
    try:
        with output.open("x", encoding="utf-8", newline="\n") as stream:
            write_record(stream, {
                "kind": "session",
                "schema_version": 1,
                "source": "东方财富公开网页行情",
                "secids": secids,
                "capture_mode": "once" if once else "window",
                "started_at": opened_at.isoformat(),
                "window_start": None if once else start.isoformat(),
                "window_end": None if once else end.isoformat(),
                "poll_delay_seconds": POLL_DELAY,
                "auction_verified": False,
            })
            with ThreadPoolExecutor(max_workers=min(4, len(secids))) as pool:
                while deadline is None or datetime.now(SHANGHAI) < deadline:
                    futures = [pool.submit(collect_when_active, secid, deadline) for secid in secids]
                    round_snapshots = 0
                    round_errors = 0
                    try:
                        for future in as_completed(futures):
                            record = future.result()
                            if record is None:
                                continue
                            kind = write_record(stream, record)
                            if kind == "snapshot":
                                snapshot_count += 1
                                round_snapshots += 1
                            else:
                                error_count += 1
                                round_errors += 1
                                print(f"{record['secid']} 采样错误，详情见样本文件。", flush=True)
                    finally:
                        for future in futures:
                            future.cancel()
                    print(
                        f"{datetime.now(SHANGHAI):%H:%M:%S} 本轮 {round_snapshots} 条原始快照 / "
                        f"{round_errors} 条错误；竞价语义仍未核验。",
                        flush=True,
                    )
                    if once:
                        break
                    remaining = (deadline - datetime.now(SHANGHAI)).total_seconds()
                    if remaining > 0:
                        time.sleep(min(POLL_DELAY, remaining))
    finally:
        print(f"已写入 {snapshot_count} 条原始快照、{error_count} 条错误：{output}", flush=True)
    return 0 if snapshot_count > 0 and error_count == 0 else 1


def main():
    parser = argparse.ArgumentParser(description="竞价原始盘口核验采样器，不提供已核验的竞价量")
    parser.add_argument("--secids", required=True, help="1至9只，逗号分隔，如1.600519,0.300750")
    parser.add_argument("--once", action="store_true", help="立即采一轮，不受时间窗口限制，仅检查连通和原始字段")
    arguments = parser.parse_args()
    secids = list(dict.fromkeys(value.strip() for value in arguments.secids.split(",")))
    if not 1 <= len(secids) <= 9:
        parser.error("每次支持1至9只不同股票")
    try:
        for secid in secids:
            validate_secid(secid)
    except ValueError as error:
        parser.error(str(error))

    now = datetime.now(SHANGHAI)
    start = now.replace(hour=9, minute=14, second=0, microsecond=0)
    end = now.replace(hour=9, minute=26, second=0, microsecond=0)
    if not arguments.once:
        if now.weekday() >= 5:
            parser.error("周末不启动常规采样；连通检查请加 --once。交易所节假日需自行核对。")
        if now >= end:
            parser.error("今日09:14—09:26采样窗口已结束；请在实际交易日上午运行，连通检查请加 --once。")
    try:
        return run_capture(secids, arguments.once, start, end)
    except KeyboardInterrupt:
        print("采样已手动停止；已写入的记录保留，未安排下次采样。", flush=True)
        return 130
    except (OSError, ValueError) as error:
        parser.exit(1, f"采样或写盘失败：{error}\n")


if __name__ == "__main__":
    raise SystemExit(main())
