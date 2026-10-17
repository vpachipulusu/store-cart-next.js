#!/usr/bin/env python3
"""CI monitoring helpers (KAN-239). Standard library only, no secrets.

  ci_stats.py slowest-junit FILE [N]   slowest test files from a JUnit XML (pytest xunit1 or vitest)
  ci_stats.py job-timing RUN_ID        per-job and per-step timing table for one workflow run
  ci_stats.py trend [WORKFLOW...]      p50/p90 duration per workflow over recent successful runs

Output is Markdown on stdout, meant for $GITHUB_STEP_SUMMARY. `job-timing` and `trend`
call `gh api` with GH_TOKEN (the job's GITHUB_TOKEN, `actions: read`).
"""

from __future__ import annotations

import json
import math
import os
import subprocess
import sys
import xml.etree.ElementTree as ET
from collections import defaultdict
from datetime import datetime

MIN_STEP_SECONDS = 5.0


def _parse(stamp: str) -> datetime:
    return datetime.fromisoformat(stamp.replace("Z", "+00:00"))


def seconds_between(start: str | None, end: str | None) -> float | None:
    if not start or not end:
        return None
    return max((_parse(end) - _parse(start)).total_seconds(), 0.0)


def percentile(values: list[float], pct: float) -> float:
    """Nearest-rank percentile; 0.0 for an empty list."""
    if not values:
        return 0.0
    ordered = sorted(values)
    rank = max(math.ceil(pct / 100 * len(ordered)), 1)
    return ordered[rank - 1]


def slowest_files(xml_text: str, limit: int = 15) -> list[tuple[str, float, int]]:
    """Sum testcase time per file. Returns (file, seconds, test count), slowest first."""
    totals: dict[str, float] = defaultdict(float)
    counts: dict[str, int] = defaultdict(int)
    root = ET.fromstring(xml_text)
    for suite in root.iter("testsuite"):
        for case in suite.iter("testcase"):
            name = case.get("file") or case.get("classname") or suite.get("name") or "unknown"
            totals[name] += float(case.get("time") or 0)
            counts[name] += 1
    ranked = sorted(totals.items(), key=lambda item: item[1], reverse=True)[:limit]
    return [(name, seconds, counts[name]) for name, seconds in ranked]


def render_slowest(title: str, rows: list[tuple[str, float, int]]) -> str:
    lines = [f"### {title}", "", "| Test file | Seconds | Tests |", "|---|---:|---:|"]
    lines += [f"| `{name}` | {seconds:.1f} | {count} |" for name, seconds, count in rows]
    return "\n".join(lines) + "\n"


def render_job_timing(jobs: list[dict]) -> str:
    lines = ["### CI timing", "", "| Job / step | Seconds |", "|---|---:|"]
    for job in jobs:
        total = seconds_between(job.get("started_at"), job.get("completed_at"))
        if total is None or job.get("conclusion") == "skipped":
            continue
        lines.append(f"| **{job['name']}** | **{total:.0f}** |")
        for step in job.get("steps", []):
            took = seconds_between(step.get("started_at"), step.get("completed_at"))
            if took is not None and took >= MIN_STEP_SECONDS:
                lines.append(f"| &nbsp;&nbsp;{step['name']} | {took:.0f} |")
    return "\n".join(lines) + "\n"


def run_durations(runs: list[dict]) -> dict[str, list[float]]:
    by_workflow: dict[str, list[float]] = defaultdict(list)
    for run in runs:
        if run.get("conclusion") != "success":
            continue
        took = seconds_between(run.get("run_started_at"), run.get("updated_at"))
        if took:
            by_workflow[run["name"]].append(took)
    return by_workflow


def render_trend(by_workflow: dict[str, list[float]]) -> str:
    lines = ["### CI duration trend", "", "| Workflow | Runs | p50 (s) | p90 (s) |", "|---|---:|---:|---:|"]
    for name, values in sorted(by_workflow.items()):
        lines.append(f"| {name} | {len(values)} | {percentile(values, 50):.0f} | {percentile(values, 90):.0f} |")
    return "\n".join(lines) + "\n"


def gh_api(path: str) -> dict:
    out = subprocess.run(["gh", "api", path], check=True, capture_output=True, text=True).stdout
    return json.loads(out)


def main(argv: list[str]) -> int:
    command = argv[1] if len(argv) > 1 else ""
    if command == "slowest-junit" and len(argv) >= 3:
        limit = int(argv[3]) if len(argv) > 3 else 15
        with open(argv[2], encoding="utf-8") as handle:
            print(render_slowest(f"Slowest {limit} test files", slowest_files(handle.read(), limit)))
        return 0
    if command == "job-timing" and len(argv) == 3:
        repo = os.environ["GITHUB_REPOSITORY"]
        jobs = gh_api(f"repos/{repo}/actions/runs/{argv[2]}/jobs?per_page=100")["jobs"]
        print(render_job_timing(jobs))
        return 0
    if command == "trend":
        repo = os.environ["GITHUB_REPOSITORY"]
        runs = gh_api(f"repos/{repo}/actions/runs?status=success&per_page=100")["workflow_runs"]
        wanted = set(argv[2:])
        by_workflow = {k: v for k, v in run_durations(runs).items() if not wanted or k in wanted}
        print(render_trend(by_workflow))
        return 0
    print(__doc__, file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv))
