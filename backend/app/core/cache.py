import time

from .runtime import CACHE, CACHE_GUARD, CACHE_LOCKS


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
