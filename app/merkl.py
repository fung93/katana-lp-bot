"""Merkl public API client (read-only) for the Katana LP incentive campaign.

Confirmed endpoint (Merkl v4)::

    GET https://api.merkl.xyz/v4/campaigns?campaignId=<id>

returns a list with one campaign object. Fields we use (verified live):

    apr                                    incentive APR as a PERCENT (e.g. 40.9)
    dailyRewards                           USD value distributed per day
    dailyRewardsBreakdown[0].amount        reward-token raw amount/day (KAT, 18 dp)
    dailyRewardsBreakdown[0].token.price   reward-token USD price
    startTimestamp / endTimestamp          unix seconds
    rewardToken.symbol / decimals          "KAT", 18
    campaignStatus.status                  processing status

The bot calls this HTTP path directly (never via MCP), per the data-source rule.
"""
from __future__ import annotations

import time
from dataclasses import dataclass

import httpx

MERKL_API_BASE = "https://api.merkl.xyz"
# vbUSDC/vbETH 0.05% incentive campaign on Katana (chain 747474).
CAMPAIGN_ID = "0xc186ab9ba208211ed853cd21a79fce531f299b8fa7850417c407b19f80c0a030"


@dataclass(frozen=True)
class CampaignStatus:
    campaign_id: str
    status: str             # e.g. "SUCCESS"
    apr_pct: float          # incentive APR, percent
    daily_usd: float        # USD value distributed per day
    daily_reward: float     # reward-token amount per day (human units)
    reward_symbol: str      # "KAT"
    reward_price_usd: float # USD price of one reward token
    start_ts: int           # unix seconds
    end_ts: int             # unix seconds

    def seconds_to_end(self, now: float | None = None) -> float:
        return self.end_ts - (time.time() if now is None else now)

    def days_to_end(self, now: float | None = None) -> float:
        return self.seconds_to_end(now) / 86400.0

    def has_ended(self, now: float | None = None) -> bool:
        return self.seconds_to_end(now) < 0

    def is_expiring(self, threshold_days: float = 7.0, now: float | None = None) -> bool:
        """True when the campaign ends within threshold_days (and hasn't ended)."""
        return 0 <= self.days_to_end(now) <= threshold_days


def parse_campaign(payload: list | dict) -> CampaignStatus:
    """Parse a /v4/campaigns response into a CampaignStatus."""
    data = payload[0] if isinstance(payload, list) else payload
    breakdown = data.get("dailyRewardsBreakdown") or []
    first = breakdown[0] if breakdown else {}
    token = first.get("token") or data.get("rewardToken") or {}
    decimals = int(token.get("decimals", 18))
    daily_reward = float(first.get("amount") or 0) / (10 ** decimals)
    status = data.get("campaignStatus")
    status_str = status.get("status") if isinstance(status, dict) else str(status or "")
    return CampaignStatus(
        campaign_id=data["campaignId"],
        status=status_str,
        apr_pct=float(data.get("apr") or 0.0),
        daily_usd=float(data.get("dailyRewards") or 0.0),
        daily_reward=daily_reward,
        reward_symbol=token.get("symbol", "?"),
        reward_price_usd=float(token.get("price") or 0.0),
        start_ts=int(data.get("startTimestamp") or 0),
        end_ts=int(data.get("endTimestamp") or 0),
    )


def fetch_campaign(
    campaign_id: str = CAMPAIGN_ID,
    base: str = MERKL_API_BASE,
    timeout: float = 15.0,
) -> CampaignStatus:
    resp = httpx.get(
        f"{base}/v4/campaigns",
        params={"campaignId": campaign_id},
        timeout=timeout,
        follow_redirects=True,
    )
    resp.raise_for_status()
    payload = resp.json()
    if not payload:
        raise RuntimeError(f"Merkl returned no campaign for {campaign_id}")
    return parse_campaign(payload)


def fetch_pool_kat(wallet: str, pool_address: str, chain_id: int = 747474,
                   reward_symbol: str = "KAT", base: str = MERKL_API_BASE,
                   timeout: float = 25.0) -> float:
    """Cumulative reward-token (KAT) the wallet has earned from one pool.

    Sums Merkl breakdown rows whose `reason` references the pool address, across
    all reward roots. The same pool runs many campaign ids over time, so we match
    on the pool address, not a single campaign id. Used as an open/close snapshot;
    a position's KAT earned is the close-minus-open difference.
    """
    resp = httpx.get(f"{base}/v4/users/{wallet}/rewards",
                     params={"chainId": chain_id}, timeout=timeout, follow_redirects=True)
    resp.raise_for_status()
    payload = resp.json()
    needle = pool_address.lower()
    total_raw = 0
    for root in (payload if isinstance(payload, list) else [payload]):
        for entry in root.get("rewards", []):
            if (entry.get("token") or {}).get("symbol") != reward_symbol:
                continue
            for b in entry.get("breakdowns", []):
                if needle in str(b.get("reason", "")).lower():
                    total_raw += int(b.get("amount", 0))
    return total_raw / 1e18


def fetch_pool_tvl(campaign_id: str = CAMPAIGN_ID, base: str = MERKL_API_BASE,
                   timeout: float = 15.0) -> float:
    """Pool TVL in USD, from the Merkl opportunities endpoint for the campaign."""
    resp = httpx.get(f"{base}/v4/opportunities", params={"campaignId": campaign_id},
                     timeout=timeout, follow_redirects=True)
    resp.raise_for_status()
    payload = resp.json()
    if not payload:
        raise RuntimeError("Merkl returned no opportunity for TVL")
    opp = payload[0] if isinstance(payload, list) else payload
    return float(opp.get("tvl") or 0.0)

