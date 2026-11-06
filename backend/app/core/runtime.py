import re
import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
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

