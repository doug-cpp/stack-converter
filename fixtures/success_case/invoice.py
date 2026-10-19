"""Invoice line-item calculation and breakdown generation (Topological Level 1)."""

from __future__ import annotations

from discounts import apply_tier_discount
from tax_rules import calculate_tax, round_currency


def compute_line_total(unit_price: float, quantity: int) -> float:
    """Calculate total for a single invoice line item."""
    if unit_price < 0.0 or quantity <= 0:
        return 0.0
    return round_currency(unit_price * quantity, 2)


def sum_line_totals(prices: list[float]) -> float:
    """Sum a list of line item totals and round to currency precision."""
    if len(prices) == 0:
        return 0.0
    total = 0.0
    for p in prices:
        if p > 0.0:
            total += p
    return round_currency(total, 2)


def compute_invoice_net_total(prices: list[float], tier: str, region: str) -> float:
    """Compute the final invoice total from line prices, customer tier, and tax region."""
    gross = sum_line_totals(prices)
    discount = apply_tier_discount(gross, tier)
    net = round_currency(max(0.0, gross - discount), 2)
    tax = calculate_tax(net, region)
    return round_currency(net + tax, 2)
