"""Deterministic TypeScript validation (tsc, eslint, tsx characterization runner) and Fixer Agent."""

from stackconverter.validate.characterization_runner import run_characterization_oracle
from stackconverter.validate.eslint import run_eslint_check
from stackconverter.validate.fixer import fix_module_code
from stackconverter.validate.tsc import run_tsc_check

__all__ = [
    "fix_module_code",
    "run_characterization_oracle",
    "run_eslint_check",
    "run_tsc_check",
]
