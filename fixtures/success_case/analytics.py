"""Revenue aggregation and customer loyalty classification (Topological Level 2)."""

from __future__ import annotations

from invoice import compute_invoice_net_total
from pricing import compute_final_price
from tax_rules import round_currency


def aggregate_revenue(revenues: list[float]) -> float:
    """Compute total revenue across a batch of completed invoices."""
    total = 0.0
    for rev in revenues:
        if rev > 0.0:
            total += rev
    return round_currency(total, 2)


def average_order_value(revenues: list[float]) -> float:
    """Calculate the mean order value for positive revenue entries."""
    valid = [r for r in revenues if r > 0.0]
    if len(valid) == 0:
        return 0.0
    return round_currency(sum(valid) / len(valid), 2)


def classify_customer_tier(annual_spend: float) -> str:
    """Recommend a loyalty tier based on trailing 12-month net spend."""
    if annual_spend >= 5000.0:
        return "platinum"
    if annual_spend >= 1500.0:
        return "gold"
    if annual_spend >= 500.0:
        return "silver"
    return "standard"


def simulate_regional_campaign(gross_amounts: list[float], tier: str, coupon_code: str, region: str) -> float:
    """Simulate total campaign net revenue across multiple carts and an invoice summary."""
    campaign_total = 0.0
    for amt in gross_amounts:
        campaign_total += compute_final_price(amt, tier, coupon_code, region)
    bonus_invoice = compute_invoice_net_total(gross_amounts, tier, region)
    return round_currency((campaign_total + bonus_invoice) / 2.0, 2)
