"""Validated public API response shapes."""

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class SourceHealth(BaseModel):
    ok: bool
    error: str | None = None
    recordCount: int = 0


class SubscriptionRow(BaseModel):
    srNo: str | int | None = None
    category: str | None = None
    sharesOffered: int | None = None
    sharesBid: int | None = None
    times: float | None = None


class Subscription(BaseModel):
    source: str
    totalTimes: float | None = None
    updatedAt: str | None = None
    nseBidDetails: list[SubscriptionRow] = Field(default_factory=list)
    consolidatedBidDetails: list[SubscriptionRow] = Field(default_factory=list)


class Quote(BaseModel):
    value: float | None = None
    percent: float | None = None


class PriceBand(BaseModel):
    min: float | None = None
    max: float | None = None


class Issue(BaseModel):
    issueKey: str
    companyName: str
    platform: str | None = None
    exchanges: list[str] = Field(default_factory=list)
    status: Literal["open", "upcoming", "closed"] | None = None
    openDate: str | None = None
    closeDate: str | None = None
    listingDate: str | None = None
    priceBand: PriceBand | None = None
    lotSize: str | int | float | None = None
    faceValue: str | int | float | None = None
    issueSize: str | int | float | None = None
    gmp: Quote | None = None
    gmpUpdatedOn: str | None = None
    detailUrl: str | None = None
    subscription: Subscription | None = None


class Overview(BaseModel):
    totalIssues: int
    openIssues: int
    upcomingIssues: int
    closedIssues: int
    quotedIssues: int
    averageGmpPercent: float | None = None
    disclosedCapitalCrore: float
    earlyGmpIssues: int


class DeliveryMeta(BaseModel):
    delivery: Literal["live", "database", "stale"]
    cacheTtlSeconds: int
    servedAt: str
    refreshInProgress: bool = False


class MarketResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    generatedAt: str
    sources: dict[str, SourceHealth]
    earlyGmp: list[dict[str, Any]]
    ipos: list[Issue]
    overview: Overview
    meta: DeliveryMeta


def _camel(value: str) -> str:
    parts = value.split("_")
    return parts[0] + "".join(part.title() for part in parts[1:])


class AnalysisModel(BaseModel):
    model_config = ConfigDict(
        alias_generator=_camel,
        populate_by_name=True,
        extra="forbid",
    )


class Citation(AnalysisModel):
    title: str
    url: str
    published_at: str | None


class Score(AnalysisModel):
    score: int
    maximum: int
    rationale: str


class IssueStructureAnalysis(AnalysisModel):
    issue_size: str
    fresh_issue: str
    ofs: str
    price_band: str
    lot_size: str
    minimum_investment: str
    use_of_proceeds: list[str]
    promoter_holding_before: str
    promoter_holding_after: str
    sources: list[Citation]


class SubscriptionAnalysis(AnalysisModel):
    qib_times: float | None
    nii_times: float | None
    retail_times: float | None
    employee_or_shareholder_times: float | None
    total_times: float | None
    as_of: str
    qib_demand_explanation: str
    qib_score: Score
    total_score: Score


class GmpAnalysis(AnalysisModel):
    current_gmp: float | None
    current_percent: float | None
    trend: str
    implied_listing_price: float | None
    expected_listing_gain: str
    score: Score
    sources: list[Citation]


class LegalFinding(AnalysisModel):
    topic: str
    stage: Literal[
        "none found",
        "allegation",
        "investigation",
        "notice",
        "order",
        "court finding",
        "conviction",
        "unavailable",
    ]
    finding: str
    points_deducted: int
    sources: list[Citation]


class LegalAnalysis(AnalysisModel):
    summary: str
    findings: list[LegalFinding]
    score: Score


class PeerComparison(AnalysisModel):
    company: str
    metrics: str
    sources: list[Citation]


class ValuationAnalysis(AnalysisModel):
    metrics: list[str]
    peers: list[PeerComparison]
    summary: str
    score: Score


class ScoredAnalysis(AnalysisModel):
    summary: str
    facts: list[str]
    score: Score
    sources: list[Citation]


class ListingGainEstimate(AnalysisModel):
    bear_case: str
    base_case: str
    bull_case: str
    expected_gain_percent: str
    expected_price_range: str


class AnalysisReport(AnalysisModel):
    data_as_of: str
    issue_structure: IssueStructureAnalysis
    subscription: SubscriptionAnalysis
    gmp: GmpAnalysis
    legal: LegalAnalysis
    valuation: ValuationAnalysis
    market: ScoredAnalysis
    industry: ScoredAnalysis
    anchor_investors: ScoredAnalysis
    fresh_ofs: ScoredAnalysis
    fundamentals: ScoredAnalysis
    total_score: int
    verdict: Literal["STRONG APPLY", "APPLY WITH CAUTION", "AVOID / WAIT", "SKIP"]
    apply_decision: Literal["APPLY", "APPLY WITH CAUTION", "SKIP"]
    hard_red_flag: bool
    hard_red_flag_reason: str
    listing_gain: ListingGainEstimate
    reasons: list[str]
    sources: list[Citation]
    data_limitations: list[str]
    disclaimer: str


class AnalysisEnvelope(AnalysisModel):
    issue_key: str
    company_name: str
    generated_at: str
    market_data_at: str
    model: str
    cached: bool
    report: AnalysisReport


class AnalysisStatus(AnalysisModel):
    configured: bool
    model: str
