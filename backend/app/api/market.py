from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse

from ..core.numbers import validate_secid
from ..providers.darkflow import get_dark_flow
from ..providers.quotes import get_quotes, get_watchlist_snapshot
from ..providers.sectors import get_sectors
from ..providers.trends import get_trends
from ..services.billboard import get_billboard
from ..services.funds import get_money_flow
from .dependencies import require_user

router = APIRouter(prefix="/api", tags=["market"], dependencies=[Depends(require_user)])


def argument(request, name, default=""):
    values = request.query_params.getlist(name)
    if len(values) > 1:
        raise HTTPException(400, "参数不能重复")
    return values[0] if values else default


def identifiers(request, limit):
    values = list(dict.fromkeys(argument(request, "secids").split(",")))
    if not 1 <= len(values) <= limit:
        raise HTTPException(400, f"每次支持1至{limit}只股票")
    return [validate_secid(value) for value in values]


@router.get("/quotes")
def quotes(request: Request):
    result = get_quotes(identifiers(request, 9))
    return JSONResponse(result, status_code=200 if result["data"] else 502)


@router.get("/watchlist-snapshot")
def watchlist_snapshot(request: Request):
    result = get_watchlist_snapshot(identifiers(request, 50))
    return JSONResponse(result, status_code=200 if result["data"] else 502)


@router.get("/trends")
def trends(request: Request):
    return get_trends(validate_secid(argument(request, "secid")))


@router.get("/money-flow")
def money_flow(request: Request):
    result = get_money_flow(validate_secid(argument(request, "secid")))
    return JSONResponse(result, status_code=200 if result["current"] is not None or result["history"] is not None else 502)


@router.get("/billboard")
def billboard(request: Request):
    return get_billboard(validate_secid(argument(request, "secid")))


@router.get("/dark-flow")
def dark_flow(request: Request):
    return get_dark_flow(validate_secid(argument(request, "secid")))


@router.get("/sectors")
def sectors(request: Request):
    market = argument(request, "market", "CN")
    kind = argument(request, "kind", "industry")
    page = argument(request, "page", "1")
    if market not in {"CN", "US"} or kind not in {"industry", "concept"} or not page.isdigit() or not 1 <= int(page) <= 1000:
        raise HTTPException(400, "市场、板块分类或页码无效")
    return get_sectors(market, kind, int(page))
