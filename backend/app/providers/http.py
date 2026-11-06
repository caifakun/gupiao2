import json
import urllib.error
import urllib.parse
import urllib.request
from http.client import HTTPException

from ..core.config import get_settings
from ..core.numbers import DataError
from ..core.runtime import MAX_BODY, UPSTREAM_LIMIT


def request_json(base_url, parameters, source):
    proxy = get_settings().market_proxy.strip()
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
