import math
import time

from .runtime import SECID_PATTERN


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
    if not isinstance(secid, str) or not SECID_PATTERN.fullmatch(secid):
        raise ValueError("证券代码格式须为1.六位沪市代码或0.六位深市代码")
    return secid
