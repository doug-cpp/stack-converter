"""Tax calculation and currency rounding primitives (Topological Level 0)."""

from __future__ import annotations


def round_currency(amount: float, decimals: int = 2) -> float:
    """Round a monetary amount deterministically to the specified decimal places."""
    if decimals < 0:
        raise ValueError("Decimals must be non-negative")
    return round(amount, decimals)


def lookup_tax_rate(region: str) -> float:
    """Return the statutory sales/VAT tax rate for a given region code."""
    code = region.strip().upper()
    if code == "US_CA":
        return 0.0825
    if code == "US_NY":
        return 0.08875
    if code == "US_OR":
        return 0.0
    if code == "EU_DE":
        return 0.19
    if code == "EU_FR":
        return 0.20
    if code == "BR_SP":
        return 0.18
    return 0.05


def calculate_tax(subtotal: float, region: str) -> float:
    """Calculate rounded tax amount for a subtotal in the given region."""
    if subtotal <= 0.0:
        return 0.0
    rate = lookup_tax_rate(region)
    return round_currency(subtotal * rate, 2)


def effective_tax_rate(subtotal: float, tax_amount: float) -> float:
    """Compute the effective tax ratio rounded to 4 decimal places."""
    if subtotal <= 0.0:
        return 0.0
    return round_currency(tax_amount / subtotal, 4)
