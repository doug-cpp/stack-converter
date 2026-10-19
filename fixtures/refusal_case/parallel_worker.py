"""CPU-bound multi-core worker pool with shared memory buffers."""

from __future__ import annotations

import multiprocessing
from concurrent.futures import ProcessPoolExecutor
from multiprocessing.shared_memory import SharedMemory


def _cpu_heavy_kernel(seed: int) -> int:
    acc = seed
    for i in range(1, 5000):
        acc = (acc * 31 + i) % 1000003
    return acc


def run_parallel_simulation(seeds: list[int], workers: int = 4) -> list[int]:
    """Dispatch CPU-bound kernels across a multi-core ProcessPoolExecutor."""
    effective_workers = min(workers, multiprocessing.cpu_count())
    shm = SharedMemory(create=True, size=64)
    try:
        with ProcessPoolExecutor(max_workers=effective_workers) as pool:
            results = list(pool.map(_cpu_heavy_kernel, seeds))
        return results
    finally:
        shm.close()
        shm.unlink()
