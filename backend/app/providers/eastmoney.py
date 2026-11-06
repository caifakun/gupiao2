from ..core.numbers import DataError
from .http import request_json


def eastmoney_data(url, parameters):
    payload = request_json(url, parameters, "eastmoney")
    data = payload.get("data")
    if payload.get("rc") != 0 or not isinstance(data, dict):
        raise DataError("东方财富未返回有效数据，证券可能不存在或接口暂不可用")
    return data
