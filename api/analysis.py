"""OpenRouter-backed, source-grounded IPO listing-gain analysis."""

from __future__ import annotations

import hashlib
import json
import logging
import os
from datetime import UTC, datetime
from typing import Any

import requests
from pydantic import ValidationError

from .database import MarketRepository
from .models import AnalysisReport

LOGGER = logging.getLogger(__name__)
OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"
DEFAULT_MODEL = "google/gemini-2.5-flash"
PROMPT_VERSION = "listing-gain-v1"


class AnalysisUnavailable(RuntimeError):
    pass


class AnalysisInProgress(RuntimeError):
    pass


class OpenRouterClient:
    def __init__(self, api_key: str | None = None, model: str | None = None):
        self.api_key = api_key or os.getenv("OPENROUTER_API_KEY")
        self.model = model or os.getenv("OPENROUTER_MODEL", DEFAULT_MODEL)
        self.site_url = os.getenv("APP_URL", "https://ipofetch.vercel.app")

    @property
    def configured(self) -> bool:
        return bool(self.api_key)

    def analyse(self, issue: dict, market_generated_at: str) -> tuple[dict, dict]:
        if not self.api_key:
            raise AnalysisUnavailable("OPENROUTER_API_KEY is not configured")

        body = self.request_body(issue, market_generated_at)
        try:
            response = requests.post(
                OPENROUTER_URL,
                headers={
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json",
                    "HTTP-Referer": self.site_url,
                    "X-OpenRouter-Title": "IPO Fetch",
                },
                json=body,
                timeout=(10, 48),
            )
            response.raise_for_status()
            payload = response.json()
            message = payload["choices"][0]["message"]
            content = message.get("content")
            if not content:
                raise AnalysisUnavailable("OpenRouter returned an empty analysis")
            parsed = _parse_json(content)
            parsed["sources"] = _merge_annotation_sources(
                parsed.get("sources", []), message.get("annotations", [])
            )
            return parsed, payload.get("usage") or {}
        except (requests.RequestException, KeyError, ValueError, TypeError) as exc:
            detail = _safe_provider_error(exc)
            raise AnalysisUnavailable(f"OpenRouter analysis failed: {detail}") from exc

    def request_body(self, issue: dict, market_generated_at: str) -> dict:
        schema = AnalysisReport.model_json_schema(by_alias=True)
        return {
            "model": self.model,
            "messages": [
                {"role": "system", "content": SYSTEM_PROMPT},
                {
                    "role": "user",
                    "content": _user_prompt(issue, market_generated_at),
                },
            ],
            "plugins": [
                {
                    "id": "web",
                    "engine": "firecrawl",
                    "mode": "deep-lite",
                    "max_results": 12,
                },
                {"id": "response-healing"},
            ],
            "response_format": {
                "type": "json_schema",
                "json_schema": {
                    "name": "ipo_listing_gain_analysis",
                    "strict": True,
                    "schema": schema,
                },
            },
            "provider": {"require_parameters": True},
            "temperature": 0.1,
            "max_tokens": 8000,
        }


class AnalysisService:
    def __init__(self, repository: MarketRepository, client: OpenRouterClient):
        self.repository = repository
        self.client = client

    def status(self) -> dict:
        return {"configured": self.client.configured, "model": self.client.model}

    def cached(self, issue_key: str) -> dict | None:
        row = self.repository.load_analysis(issue_key)
        return _envelope(row, cached=True) if row else None

    def generate(
        self, issue: dict, market_generated_at: str, force: bool = False
    ) -> dict:
        if issue.get("status") == "closed":
            raise AnalysisUnavailable(
                "Listing-gain analysis is available only while an IPO is open or upcoming"
            )
        if not self.client.configured:
            raise AnalysisUnavailable("OPENROUTER_API_KEY is not configured")

        fingerprint = analysis_fingerprint(issue, self.client.model)
        if not force:
            cached = self.repository.load_analysis(issue["issueKey"], fingerprint)
            if cached:
                return _envelope(cached, cached=True)

        token = self.repository.start_analysis(issue["issueKey"], fingerprint, force)
        if token is None:
            cached = self.repository.load_analysis(issue["issueKey"])
            if cached:
                return _envelope(cached, cached=True)
            raise AnalysisInProgress(
                "Analysis is already running or was refreshed in the last 30 minutes"
            )

        try:
            raw_report, usage = self.client.analyse(issue, market_generated_at)
            report = AnalysisReport.model_validate(raw_report)
            report = _finalize_report(report, issue, market_generated_at)
            row = self.repository.save_analysis(
                token=token,
                issue_key=issue["issueKey"],
                company_name=issue["companyName"],
                fingerprint=fingerprint,
                model=self.client.model,
                market_generated_at=market_generated_at,
                report=report.model_dump(mode="json", by_alias=True),
                usage=usage,
            )
            return _envelope(row, cached=False)
        except ValidationError as exc:
            self.repository.fail_analysis(issue["issueKey"], token)
            raise AnalysisUnavailable(
                "The model returned an incomplete report; please retry later"
            ) from exc
        except Exception:
            self.repository.fail_analysis(issue["issueKey"], token)
            raise


def analysis_fingerprint(issue: dict, model: str) -> str:
    fields = {
        key: issue.get(key)
        for key in (
            "issueKey",
            "companyName",
            "status",
            "openDate",
            "closeDate",
            "listingDate",
            "priceBand",
            "lotSize",
            "issueSize",
            "gmp",
            "gmpUpdatedOn",
            "subscription",
        )
    }
    canonical = json.dumps(
        {"version": PROMPT_VERSION, "model": model, "issue": fields},
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(canonical.encode()).hexdigest()


def _finalize_report(
    report: AnalysisReport, issue: dict, market_generated_at: str
) -> AnalysisReport:
    """Apply deterministic rubric rules to the model's researched report."""
    subscription = _subscription_metrics(issue)
    report.data_as_of = market_generated_at
    report.subscription.qib_times = subscription["qib"]
    report.subscription.nii_times = subscription["nii"]
    report.subscription.retail_times = subscription["retail"]
    report.subscription.employee_or_shareholder_times = subscription["other"]
    report.subscription.total_times = subscription["total"]
    report.subscription.as_of = (issue.get("subscription") or {}).get(
        "updatedAt"
    ) or market_generated_at
    report.subscription.qib_score.score = _qib_score(subscription["qib"])
    report.subscription.qib_score.maximum = 20
    report.subscription.total_score.score = _total_score(subscription["total"])
    report.subscription.total_score.maximum = 10

    gmp = issue.get("gmp") or {}
    if gmp.get("value") is not None:
        report.gmp.current_gmp = float(gmp["value"])
    if gmp.get("percent") is not None:
        report.gmp.current_percent = float(gmp["percent"])
        report.gmp.score.score = _gmp_score(report.gmp.current_percent)
    report.gmp.score.maximum = 20

    weighted = [
        (report.subscription.qib_score, 20),
        (report.gmp.score, 20),
        (report.legal.score, 25),
        (report.subscription.total_score, 10),
        (report.valuation.score, 8),
        (report.market.score, 5),
        (report.industry.score, 3),
        (report.anchor_investors.score, 4),
        (report.fresh_ofs.score, 3),
        (report.fundamentals.score, 2),
    ]
    total = 0
    for score, maximum in weighted:
        score.maximum = maximum
        score.score = max(0, min(score.score, maximum))
        total += score.score
    report.total_score = total

    if report.hard_red_flag:
        report.verdict = "SKIP"
        report.apply_decision = "SKIP"
    elif total >= 80 and report.legal.score.score >= 10:
        report.verdict = "STRONG APPLY"
        report.apply_decision = "APPLY"
    elif total >= 65:
        report.verdict = "APPLY WITH CAUTION"
        report.apply_decision = "APPLY WITH CAUTION"
    elif total >= 50:
        report.verdict = "AVOID / WAIT"
        report.apply_decision = "SKIP"
    else:
        report.verdict = "SKIP"
        report.apply_decision = "SKIP"
    report.disclaimer = (
        "AI-assisted research for informational purposes only, not investment advice. "
        "Verify the RHP, exchange notices and your broker before applying."
    )
    return report


def _subscription_metrics(issue: dict) -> dict[str, float | None]:
    subscription = issue.get("subscription") or {}
    rows = subscription.get("consolidatedBidDetails") or subscription.get(
        "nseBidDetails", []
    )
    values: dict[str, float | None] = {
        "qib": None,
        "nii": None,
        "retail": None,
        "other": None,
        "total": _float(subscription.get("totalTimes")),
    }
    for row in rows:
        category = str(row.get("category") or "").lower()
        value = _float(row.get("times"))
        if value is None:
            continue
        if "qualified institutional" in category or "qib" in category:
            values["qib"] = value
        elif (
            "non institutional" in category
            or "non-institutional" in category
            or "nii" in category
        ):
            values["nii"] = value
        elif "retail" in category:
            values["retail"] = value
        elif "employee" in category or "shareholder" in category:
            values["other"] = max(values["other"] or 0, value)
        elif "total" in category and values["total"] is None:
            values["total"] = value
    return values


def _qib_score(value: float | None) -> int:
    if value is None or value < 1:
        return 0
    if value < 2:
        return 5
    if value < 5:
        return 10
    if value < 10:
        return 14
    if value < 25:
        return 17
    if value <= 50:
        return 19
    return 20


def _total_score(value: float | None) -> int:
    if value is None or value < 1:
        return 0
    if value < 2:
        return 3
    if value < 5:
        return 5
    if value < 10:
        return 7
    if value < 25:
        return 8
    if value <= 50:
        return 9
    return 10


def _gmp_score(value: float | None) -> int:
    if value is None or value < 0:
        return 0
    if value <= 2:
        return 5
    if value <= 5:
        return 8
    if value <= 10:
        return 12
    if value <= 20:
        return 16
    if value <= 30:
        return 18
    return 20


def _float(value: Any) -> float | None:
    try:
        return float(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def _parse_json(content: Any) -> dict:
    if isinstance(content, list):
        content = "".join(
            part.get("text", "") for part in content if isinstance(part, dict)
        )
    text = str(content).strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[-1].rsplit("```", 1)[0]
    value = json.loads(text)
    if not isinstance(value, dict):
        raise TypeError("analysis was not a JSON object")
    return value


def _merge_annotation_sources(sources: list, annotations: list) -> list:
    merged = list(sources) if isinstance(sources, list) else []
    seen = {source.get("url") for source in merged if isinstance(source, dict)}
    for annotation in annotations or []:
        citation = annotation.get("url_citation") or {}
        url = citation.get("url")
        if url and url not in seen:
            merged.append(
                {
                    "title": citation.get("title") or url,
                    "url": url,
                    "publishedAt": None,
                }
            )
            seen.add(url)
    return merged


def _safe_provider_error(exc: Exception) -> str:
    if isinstance(exc, requests.HTTPError) and exc.response is not None:
        try:
            message = exc.response.json().get("error", {}).get("message")
            if message:
                return str(message)[:300]
        except (ValueError, AttributeError):
            pass
        return f"HTTP {exc.response.status_code}"
    return str(exc)[:300]


def _envelope(row: dict, cached: bool) -> dict:
    generated = row["generated_at"]
    if isinstance(generated, datetime):
        generated = generated.astimezone(UTC).isoformat().replace("+00:00", "Z")
    return {
        "issueKey": row["issue_key"],
        "companyName": row["company_name"],
        "generatedAt": generated,
        "marketDataAt": row["market_generated_at"],
        "model": row["model"],
        "cached": cached,
        "report": row["report"],
    }


SYSTEM_PROMPT = """You are a cautious Indian IPO research analyst. Analyse only for short-term listing gains, never long-term investing. Use current web research and prioritise SEBI, NSE/BSE, the issuer RHP/DRHP, court/regulator records, company filings, and reputable financial publications. Treat the application-supplied NSE subscription snapshot as authoritative and never replace it with a web value. Clearly separate facts from analysis. Never invent unavailable information. Distinguish allegation, investigation, notice, regulatory order, court finding and conviction. Every material current claim must have a source. Return only the requested JSON schema."""


def _user_prompt(issue: dict, market_generated_at: str) -> str:
    snapshot = json.dumps(issue, ensure_ascii=False, separators=(",", ":"))
    return f"""Analyse {issue.get("companyName")} strictly for whether a retail investor should apply for listing gains. Current date: {datetime.now(UTC).date().isoformat()}.

AUTHORITATIVE APPLICATION DATA (generated {market_generated_at}):
{snapshot}

Research the latest RHP/DRHP/prospectus and current sources. Fill every schema field; use \"data unavailable\" and null values rather than guessing.

Scoring rubric (exact):
- QIB /20: <1x=0, 1-2x=5, 2-5x=10, 5-10x=14, 10-25x=17, 25-50x=19, >50x=20.
- GMP /20: negative=0, 0-2%=5, 2-5%=8, 5-10%=12, 10-20%=16, 20-30%=18, >30%=20. Analyse the trend and multiple sources, not only today's number.
- Rules/compliance/legal /25. Investigate SEBI, MCA/company-law, income-tax, GST, customs/CBIC, RBI/regulatory issues, criminal cases/FIRs, EOW cases, fraud/cheating/forgery/bribery allegations, material litigation, promoter/director cases or disqualification, auditor qualifications/resignation, accounting irregularities, related parties, governance, licences, contingent liabilities and government investigations. List material checks separately with their legal stage and exact deductions. 25 clean; 20-24 low; 15-19 moderate; 10-14 high; below 10 severe.
- Total subscription /10: <1x=0, 1-2x=3, 2-5x=5, 5-10x=7, 10-25x=8, 25-50x=9, >50x=10.
- Valuation /8: P/E, P/B, EV/EBITDA where relevant, ROE, ROCE, EPS, debt/equity, growth and margin; compare 3-5 genuinely relevant listed peers.
- Market /5: NIFTY trend, broad sentiment, recent IPOs, volatility and sector.
- Industry /3: hot, neutral or weak.
- Anchor investors /4: amount, quality, mutual funds, foreign institutions and concentration.
- Fresh issue/OFS /3: productive use, debt repayment, promoter/investor selling and excessive OFS.
- Fundamentals /2: growth, margins, cash flow, debt and business quality.

The weights total 100. Recommend STRONG APPLY for 80-100, APPLY WITH CAUTION for 65-79, AVOID / WAIT for 50-64 and SKIP below 50. If legal is below 10/25, never return STRONG APPLY. A genuine hard red flag may override the numerical result. Include bear/base/bull listing cases, expected gain and expected price range, 5-10 concise decision reasons, limitations, and deduplicated sources with direct URLs. This is research, not a guarantee."""
