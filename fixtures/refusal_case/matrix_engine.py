"""Core scientific matrix solver using numpy and pandas vectorization."""

from __future__ import annotations

import ctypes

import numpy as np
import pandas as pd


def compute_covariance_eigenvalues(records: list[dict[str, float]]) -> list[float]:
    """Compute eigenvalues of a covariance matrix using numpy/pandas C extensions."""
    df = pd.DataFrame(records)
    matrix = df.to_numpy(dtype=np.float64)
    cov = np.cov(matrix, rowvar=False)
    eigenvalues, _ = np.linalg.eigh(cov)
    return [float(x) for x in eigenvalues]


def allocate_aligned_buffer(size_bytes: int) -> ctypes.Array[ctypes.c_char]:
    """Allocate a raw C buffer via ctypes for zero-copy native SIMD operations."""
    return ctypes.create_string_buffer(size_bytes)
