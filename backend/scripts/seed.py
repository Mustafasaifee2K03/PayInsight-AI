"""(Re)generate the deterministic demo databases for every scenario profile.

Usage:
    .venv\\Scripts\\python scripts\\seed.py            # create missing profile databases
    .venv\\Scripts\\python scripts\\seed.py --reset    # rebuild all profiles from scratch
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.config import get_settings  # noqa: E402
from app.services.auth import seed_demo_users  # noqa: E402
from app.database.app_store import init_app_store  # noqa: E402
from app.database.generator import PROFILES, build_database  # noqa: E402


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--reset", action="store_true", help="rebuild every profile even if it exists")
    args = ap.parse_args()
    s = get_settings()
    init_app_store()
    seed_demo_users()
    print(f"Data directory: {s.data_dir}")
    print(f"Window: {s.data_start_date} -> {s.data_end_date}  rows/profile: {s.default_row_count:,}  seed: {s.random_seed}")
    for profile in PROFILES:
        path = s.payments_db_path(profile)
        if path.exists() and not args.reset:
            print(f"  {profile:<20} exists  ({path.name})")
            continue
        r = build_database(path, profile, s.default_row_count, s.random_seed, s.data_start_date, s.data_days)
        print(f"  {profile:<20} built   {r.raw_rows:>7,} raw / {r.canonical_rows:>7,} canonical rows in {r.seconds:.2f}s")
    print("Demo users ready: admin@payinsight.demo, analyst@payinsight.demo, viewer@payinsight.demo")


if __name__ == "__main__":
    main()
