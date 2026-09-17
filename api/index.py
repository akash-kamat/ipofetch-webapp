"""FastAPI application used locally and by Vercel's Python runtime."""

from __future__ import annotations

import re
from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Response
from fastapi.responses import FileResponse

from .database import MarketRepository
from .models import Issue, MarketResponse
from .service import MarketService, MarketUnavailable

ROOT = Path(__file__).resolve().parents[1]
load_dotenv(ROOT / ".env")

app = FastAPI(
    title="IPO market API",
    version="2.0.0",
    docs_url="/api/docs",
    openapi_url="/api/openapi.json",
)

service = MarketService(MarketRepository())


def get_market(force: bool = False) -> dict:
    try:
        return service.get_market(force=force)
    except MarketUnavailable as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@app.get("/api/market", response_model=MarketResponse)
def market(response: Response):
    response.headers["Cache-Control"] = "private, max-age=0, must-revalidate"
    return get_market()


@app.post("/api/refresh", response_model=MarketResponse)
def refresh_market(response: Response):
    response.headers["Cache-Control"] = "no-store"
    return get_market(force=True)


@app.get("/api/ipos/{company_key}", response_model=Issue)
def ipo_detail(company_key: str):
    key = re.sub(r"[^a-z0-9]", "", company_key.lower())
    for ipo in get_market().get("ipos", []):
        if ipo.get("issueKey") == key:
            return ipo
        candidate = re.sub(r"[^a-z0-9]", "", ipo.get("companyName", "").lower())
        if candidate == key:
            return ipo
    raise HTTPException(status_code=404, detail="IPO not found")


@app.get("/api/health")
def health():
    return {"ok": True, "service": "ipo-market-api"}


@app.get("/", include_in_schema=False)
def frontend():
    return FileResponse(ROOT / "index.html")


@app.get("/app.js", include_in_schema=False)
def frontend_js():
    return FileResponse(ROOT / "app.js", media_type="application/javascript")


@app.get("/styles.css", include_in_schema=False)
def frontend_css():
    return FileResponse(ROOT / "styles.css", media_type="text/css")
