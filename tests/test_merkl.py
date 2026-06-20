"""Offline tests for Merkl campaign parsing and expiry logic.

Uses a captured sample of the real /v4/campaigns response (trimmed), so the
tests need no network and are deterministic.
"""
from __future__ import annotations

from app.merkl import parse_campaign

# Trimmed from a live response for campaign 0xc186...030 (vbUSDC/vbETH 0.05%).
SAMPLE = [
    {
        "campaignId": "0xc186ab9ba208211ed853cd21a79fce531f299b8fa7850417c407b19f80c0a030",
        "apr": 40.91606083514453,
        "dailyRewards": 424.01342519201313,
        "startTimestamp": 1781132401,
        "endTimestamp": 1782342000,
        "rewardToken": {"symbol": "KAT", "decimals": 18, "price": 0.005805988324335453},
        "campaignStatus": {"status": "SUCCESS"},
        "dailyRewardsBreakdown": [
            {
                "amount": "73030361327938985525248",
                "token": {"symbol": "KAT", "decimals": 18, "price": 0.005805988324335453},
                "value": 424.01342519201313,
            }
        ],
    }
]


def test_parse_values() -> None:
    c = parse_campaign(SAMPLE)
    assert c.reward_symbol == "KAT"
    assert round(c.apr_pct, 1) == 40.9
    assert abs(c.daily_reward - 73030.36) < 0.5      # KAT amount/day from breakdown
    assert round(c.daily_usd) == 424                 # USD value/day
    assert round(c.reward_price_usd, 4) == 0.0058
    assert c.end_ts == 1782342000


def test_expiry_logic() -> None:
    c = parse_campaign(SAMPLE)
    four_days_before = 1782342000 - 4 * 86400
    assert round(c.days_to_end(now=four_days_before), 1) == 4.0
    assert c.is_expiring(7, now=four_days_before)
    assert not c.is_expiring(2, now=four_days_before)
    assert not c.has_ended(now=four_days_before)


def test_after_end() -> None:
    c = parse_campaign(SAMPLE)
    after = 1782342000 + 100
    assert c.has_ended(now=after)
    assert not c.is_expiring(7, now=after)   # ended -> negative days -> not "expiring"


def test_parse_accepts_bare_dict() -> None:
    # Endpoint returns a list, but parse should also accept a single object.
    c = parse_campaign(SAMPLE[0])
    assert c.campaign_id.startswith("0xc186")
