"""Order pricing calculator combining discounts and regional tax rules (Topological Level 1)."""

from __future__ import annotations

from discounts import best_discount
from tax_rules import calculate_tax, round_currency


def compute_discounted_subtotal(gross_subtotal: float, tier: str, coupon_code: str) -> float:
    """Compute the net subtotal after applying the best eligible discount."""
    if gross_subtotal <= 0.0:
        return 0.0
    disc = best_discount(gross_subtotal, tier, coupon_code)
    return round_currency(max(0.0, gross_subtotal - disc), 2)


def compute_final_price(gross_subtotal: float, tier: str, coupon_code: str, region: str) -> float:
    """Compute final payable price including loyalty/coupon discounts and regional tax."""
    net_subtotal = compute_discounted_subtotal(gross_subtotal, tier, coupon_code)
    tax = calculate_tax(net_subtotal, region)
    return round_currency(net_subtotal + tax, 2)


def estimate_bulk_unit_price(unit_price: float, quantity: int) -> float:
    """Compute volume-discounted unit price based on quantity brackets."""
    if unit_price <= 0.0 or quantity <= 0:
        return 0.0
    if quantity >= 100:
        return round_currency(unit_price * 0.85, 2)
    if quantity >= 25:
        return round_currency(unit_price * 0.92, 2)
    if quantity >= 10:
        return round_currency(unit_price * 0.96, 2)
    return round_currency(unit_price, 2)
