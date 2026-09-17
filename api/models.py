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
