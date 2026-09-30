#!/usr/bin/env python3
"""Reproducible msxdbg benchmarks; live measurements are explicit opt-in."""
from __future__ import annotations

import argparse
import json
import statistics
import time
from pathlib import Path

from msxdbg.debuginfo.loader import ImageSpec, ProjectLoader, ProjectSpec
from msxdbg.debuginfo.model import ImageId
from msxdbg.target.api import TargetCapabilities
from msxdbg.target.openmsx import OpenMSXTarget
from msxdbg.target.transport import OpenMSXTransport, TransportConfig, discover_socket


def measure(action, iterations: int) -> dict[str, float]:
    samples = []
    for _ in range(iterations):
        started = time.perf_counter_ns()
        action()
        samples.append((time.perf_counter_ns() - started) / 1_000_000)
    ordered = sorted(samples)
    p95 = ordered[min(len(ordered) - 1, int(len(ordered) * 0.95))]
    return {"iterations": iterations, "median_ms": statistics.median(samples),
            "p95_ms": p95, "max_ms": max(samples)}


def attach_once(socket_path: Path) -> None:
    transport = OpenMSXTransport(TransportConfig(socket_path, 5.0))
    try:
        response = transport.request("expr 0")
        if response.status != "ok":
            raise RuntimeError("openMSX attach probe was rejected")
    finally:
        transport.close()


def step_and_wait(target: OpenMSXTarget, timeout: float = 5.0) -> None:
    target.step_into()
    deadline = time.monotonic() + timeout
    while target.execution_status().value != "stopped":
        if time.monotonic() >= deadline:
            raise TimeoutError("openMSX did not stop after step_into")
        time.sleep(0.001)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", type=Path, required=True,
                        help="real SDCC output directory used for project loading")
    parser.add_argument("--iterations", type=int, default=20)
    parser.add_argument("--socket", type=Path,
                        help="operator-prepared openMSX; enables live benchmarks")
    parser.add_argument("--allow-step", action="store_true",
                        help="perform one instruction step per live iteration")
    args = parser.parse_args()
    if args.iterations < 1:
        parser.error("--iterations must be positive")

    spec = ProjectSpec((ImageSpec(ImageId(args.out.name), args.out),))
    results = {"format_version": 1, "iterations": args.iterations,
               "project_load": measure(lambda: ProjectLoader().load(spec), args.iterations)}

    if args.socket is not None:
        socket_path = discover_socket(args.socket)
        results["attach"] = measure(
            lambda: attach_once(socket_path),
            args.iterations)
        transport = OpenMSXTransport(TransportConfig(socket_path, 5.0, "persistent"))
        target = OpenMSXTarget(transport, TargetCapabilities(persistent=True, block_read=True))
        try:
            results["memory_256"] = measure(lambda: target.read_memory(0, 256), args.iterations)
            if args.allow_step:
                results["step_into_stop"] = measure(lambda: step_and_wait(target), args.iterations)
        finally:
            target.close()

    print(json.dumps(results, sort_keys=True, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
