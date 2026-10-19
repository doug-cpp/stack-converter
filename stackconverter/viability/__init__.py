"""Viability Gate: AST detectors, Unified Dialectical Judge Agent, and deterministic verdict rules."""

from stackconverter.viability.judge import run_dialectical_judge
from stackconverter.viability.verdict_rules import compute_verdict

__all__ = ["compute_verdict", "run_dialectical_judge"]
