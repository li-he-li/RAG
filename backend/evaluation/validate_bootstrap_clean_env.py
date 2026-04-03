"""
Validate first-run bootstrap flow in a clean runtime environment.

Validation approach:
1) Remove managed PostgreSQL/Qdrant containers if they exist.
2) Execute bootstrap.
3) Verify components are ready and containers are recreated/running.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import time
from pathlib import Path

from app.core.config import (
    PG_DOCKER_NAME,
    QDRANT_DOCKER_NAME,
    run_bootstrap,
)


def _run(cmd: list[str]) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, capture_output=True, text=True)


def _container_exists(name: str) -> bool:
    result = _run(["docker", "ps", "-a", "--filter", f"name={name}", "--format", "{{.Names}}"])
    return name in result.stdout.strip().splitlines()


def _container_running(name: str) -> bool:
    result = _run(["docker", "ps", "--filter", f"name={name}", "--format", "{{.Names}}"])
    return name in result.stdout.strip().splitlines()


def _remove_container_if_exists(name: str) -> bool:
    if not _container_exists(name):
        return False
    _run(["docker", "rm", "-f", name])
    return True


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--json-out",
        default="evaluation/bootstrap_clean_env_report.json",
        help="Output JSON report path",
    )
    args = parser.parse_args()

    targets = [PG_DOCKER_NAME, QDRANT_DOCKER_NAME]
    before = {name: {"exists": _container_exists(name), "running": _container_running(name)} for name in targets}
    removed = {name: _remove_container_if_exists(name) for name in targets}

    t0 = time.perf_counter()
    status = run_bootstrap()
    elapsed_sec = time.perf_counter() - t0

    after = {name: {"exists": _container_exists(name), "running": _container_running(name)} for name in targets}

    report = {
        "validated_at_epoch": time.time(),
        "elapsed_sec": elapsed_sec,
        "bootstrap_status": status,
        "containers_before": before,
        "containers_removed_for_clean_start": removed,
        "containers_after": after,
        "all_ready": bool(status.get("all_ready", False)),
    }

    out_path = Path(args.json_out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["all_ready"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
