"""Performance benchmark: SQL-layer and end-to-end timings on 30k and 100k datasets.

Usage:  .venv\\Scripts\\python scripts\\benchmark.py [--repeats 7]
Writes docs/generated/benchmark_results.json and the BENCH section of docs/BENCHMARK_REPORT.md.
All numbers are measured on the machine that runs this script; nothing is estimated.
"""
from __future__ import annotations

import argparse
import json
import os
import platform
import re
import statistics
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
os.environ.setdefault("PAYINSIGHT_LOG_LEVEL", "WARNING")

from app.config import PROJECT_DIR, get_settings  # noqa: E402
from app.core.logging import configure_logging  # noqa: E402
from app.core.security import DEMO_USERS, Role, User  # noqa: E402
from app.database.app_store import init_app_store  # noqa: E402
from app.database.generator import build_database  # noqa: E402
from app.database.manager import get_db  # noqa: E402
from app.schemas.plan import AnalysisPlan, TimeRange  # noqa: E402
from app.services import analysis  # noqa: E402
from app.services.query_executor import cache, execute  # noqa: E402
from app.services.sql_compiler import compile_aggregate, compile_period_segments  # noqa: E402


def timed(fn, repeats: int, clear_cache: bool = True):
    samples = []
    for _ in range(repeats):
        if clear_cache:
            cache.clear()
        t0 = time.perf_counter()
        fn()
        samples.append((time.perf_counter() - t0) * 1000)
    return {"median_ms": round(statistics.median(samples), 2), "min_ms": round(min(samples), 2), "max_ms": round(max(samples), 2), "n": repeats}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--repeats", type=int, default=7)
    args = ap.parse_args()
    configure_logging("WARNING")
    init_app_store()
    s = get_settings()
    end = s.data_end_date
    full = TimeRange(start=s.data_start_date, end=end, label="full")
    cur = TimeRange(start=end - timedelta(days=6), end=end, label="last 7 days")
    prev = TimeRange(start=end - timedelta(days=13), end=end - timedelta(days=7), label="previous 7 days")
    p_full = AnalysisPlan(intent="kpi", metric="success_rate", time_range=full)
    p_cmp = AnalysisPlan(intent="period_comparison", metric="success_rate", time_range=cur, comparison="previous_period", comparison_range=prev)
    user = User(0, DEMO_USERS[1][0], "Benchmark", Role.ANALYST)

    sql_cases = {
        "Overall success rate (full window)": lambda: execute(compile_aggregate(p_full, dimensions=[], purpose="bench")),
        "Daily transaction aggregation (60 days)": lambda: execute(compile_aggregate(p_full, dimensions=["day"], purpose="bench", order="day ASC")),
        "Bank-level breakdown": lambda: execute(compile_aggregate(p_full, dimensions=["bank"], purpose="bench")),
        "Previous-period comparison (7d vs 7d)": lambda: execute(compile_period_segments(p_cmp, None, purpose="bench")),
        "Multi-dimensional (bank x payment method)": lambda: execute(compile_aggregate(p_full, dimensions=["bank", "payment_method"], purpose="bench", limit=500)),
        "Period comparison by bank (segmented)": lambda: execute(compile_period_segments(p_cmp, "bank", purpose="bench")),
    }
    e2e_cases = {
        "E2E: 'What is the overall success rate?'": "What is the overall success rate?",
        "E2E: 'Compare payment success rates by bank'": "Compare payment success rates by bank",
        "E2E: 'Why did payment success rate decline?'": "Why did payment success rate decline?",
    }

    results = {"run_at": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
               "machine": f"{platform.system()} {platform.release()}, Python {platform.python_version()}, {platform.processor() or platform.machine()}",
               "repeats": args.repeats, "datasets": []}
    db = get_db()
    for rows in (30_000, 100_000):
        path = s.data_dir / f"bench_{rows // 1000}k.db"
        t0 = time.perf_counter()
        gen = build_database(path, "bank_decline", rows, s.random_seed, s.data_start_date, s.data_days)
        gen_s = time.perf_counter() - t0
        db.use_path(path)
        ds = {"rows": rows, "file_mb": round(path.stat().st_size / 1e6, 1), "generation_s": round(gen_s, 2), "cases": {}}
        for name, fn in sql_cases.items():
            ds["cases"][name] = timed(fn, args.repeats)
        # repeated query -> cache hit
        cache.clear()
        sql_cases["Bank-level breakdown"]()
        ds["cases"]["Repeated bank breakdown (cache hit)"] = timed(sql_cases["Bank-level breakdown"], args.repeats, clear_cache=False)
        analysis.run_analysis("What is the overall success rate?", user)  # warm planner catalogue
        for name, q in e2e_cases.items():
            ds["cases"][name + " (cold cache)"] = timed(lambda q=q: analysis.run_analysis(q, user), max(3, args.repeats // 2))
        ds["cases"]["E2E: 'Why did payment success rate decline?' (warm cache)"] = timed(
            lambda: analysis.run_analysis("Why did payment success rate decline?", user), max(3, args.repeats // 2), clear_cache=False)
        results["datasets"].append(ds)
        print(f"{rows:,} rows: generated in {gen_s:.2f}s ({gen.raw_rows} raw rows)")
        for k, v in ds["cases"].items():
            print(f"  {k:<62} median {v['median_ms']:>8.2f} ms  (min {v['min_ms']}, max {v['max_ms']})")
    db.activate("baseline")
    for rows in (30_000, 100_000):
        try:
            (s.data_dir / f"bench_{rows // 1000}k.db").unlink()
        except OSError:
            pass

    gen_dir = PROJECT_DIR / "docs" / "generated"
    gen_dir.mkdir(parents=True, exist_ok=True)
    (gen_dir / "benchmark_results.json").write_text(json.dumps(results, indent=2), encoding="utf-8")
    a, b = results["datasets"]
    lines = [f"_Generated by `scripts/benchmark.py` on {results['run_at']} — {results['machine']}; median of {results['repeats']} runs (E2E: median of {max(3, results['repeats'] // 2)})._", "",
             f"Dataset generation (batched inserts, incl. indexes and canonical snapshot): **30k rows {a['generation_s']} s ({a['file_mb']} MB)**, **100k rows {b['generation_s']} s ({b['file_mb']} MB)**.", "",
             "| Benchmark | 30k median (ms) | 30k min–max | 100k median (ms) | 100k min–max |", "|---|---|---|---|---|"]
    for k in a["cases"]:
        x, y = a["cases"][k], b["cases"][k]
        lines.append(f"| {k} | {x['median_ms']} | {x['min_ms']}–{x['max_ms']} | {y['median_ms']} | {y['min_ms']}–{y['max_ms']} |")
    report = PROJECT_DIR / "docs" / "BENCHMARK_REPORT.md"
    text = report.read_text(encoding="utf-8")
    block = "<!-- BENCH:START -->\n" + "\n".join(lines) + "\n<!-- BENCH:END -->"
    report.write_text(re.sub(r"<!-- BENCH:START -->.*?<!-- BENCH:END -->", lambda _: block, text, flags=re.S), encoding="utf-8")
    print(f"Wrote {report}")


if __name__ == "__main__":
    main()
