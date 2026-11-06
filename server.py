import argparse
import os

from backend.app.core.numbers import DataError, source_timestamp, validate_secid
from backend.app.core.runtime import ROOT, SHANGHAI
from backend.app.providers.eastmoney import eastmoney_data


def main():
    import uvicorn
    parser = argparse.ArgumentParser(description="竞观FastAPI服务；前端请使用Vite或Nginx提供")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--local", action="store_true", help="本机免登录模式，不连接数据库，自选保存在浏览器")
    args = parser.parse_args()
    if not 1 <= args.port <= 65535:
        parser.error("端口须为1至65535")
    if args.local:
        os.environ["APP_MODE"] = "local"
        os.environ.setdefault("PUBLIC_ORIGIN", f"http://127.0.0.1:{args.port}")
        print(f"本机模式：http://127.0.0.1:{args.port}（无登录、无数据库，自选仅存当前浏览器）", flush=True)
    uvicorn.run("backend.app.main:app", host="127.0.0.1", port=args.port, workers=1, proxy_headers=True, forwarded_allow_ips="127.0.0.1")


if __name__ == "__main__":
    main()
