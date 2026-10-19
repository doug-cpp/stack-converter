"""Customer tier and promotional coupon discount logic (Topological Level 0)."""

from __future__ import annotations


def tier_discount_rate(tier: str) -> float:
    """Return the fractional discount rate associated with a customer loyalty tier."""
    normalized = tier.strip().lower()
    if normalized == "platinum":
        return 0.15
    if normalized == "gold":
        return 0.10
    if normalized == "silver":
        return 0.05
    return 0.0


def apply_tier_discount(subtotal: float, tier: str) -> float:
    """Compute the discount amount granted by a customer loyalty tier."""
    if subtotal <= 0.0:
        return 0.0
    rate = tier_discount_rate(tier)
    return round(subtotal * rate, 2)


def coupon_discount_amount(subtotal: float, coupon_code: str) -> float:
    """Calculate the promotional discount for a coupon code."""
    if subtotal <= 0.0:
        return 0.0
    code = coupon_code.strip().upper()
    if code == "SAVE10":
        return round(subtotal * 0.10, 2)
    if code == "WELCOME20":
        return min(round(subtotal * 0.20, 2), 50.0)
    if code == "FLAT15":
        return 15.0 if subtotal >= 75.0 else 0.0
    return 0.0


def best_discount(subtotal: float, tier: str, coupon_code: str) -> float:
    """Return the best combined discount capped at 30% of subtotal."""
    if subtotal <= 0.0:
        return 0.0
    tier_amt = apply_tier_discount(subtotal, tier)
    coupon_amt = coupon_discount_amount(subtotal, coupon_code)
    combined = tier_amt + coupon_amt * 0.5 if tier_amt > 0.0 and coupon_amt > 0.0 else max(tier_amt, coupon_amt)
    cap = round(subtotal * 0.30, 2)
    return round(min(combined, cap), 2)
