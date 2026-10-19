"""Orchestrator combining CPU-bound multiprocessing and dynamic formula eval."""

from __future__ import annotations

from matrix_engine import compute_covariance_eigenvalues
from parallel_worker import run_parallel_simulation


def evaluate_dynamic_kernel(formula: str, x: float) -> float:
    """Dynamically evaluate user-supplied mathematical kernel via eval()."""
    return float(eval(formula, {"__builtins__": {}}, {"x": x}))


def run_quant_pipeline(records: list[dict[str, float]], seeds: list[int]) -> dict[str, list[float]]:
    """Run the full quantitative simulation pipeline."""
    eigs = compute_covariance_eigenvalues(records)
    sim = [float(v) for v in run_parallel_simulation(seeds)]
    return {"eigenvalues": eigs, "simulation": sim}
