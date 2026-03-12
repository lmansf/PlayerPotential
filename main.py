"""
PlayerPotential — NA Top-1000 Ranked Solo Stats
================================================

Usage
-----
    # First: copy .env.example to .env and set your RIOT_API_KEY
    python main.py

Optional flags
--------------
    --top N          Number of players to fetch (default: 1000)
    --concurrency N  Max simultaneous API requests (default: 40)
    --no-parquet     Write CSV only (skip Parquet)
    --csv            Also write a CSV alongside the Parquet output
"""

import argparse
import asyncio
import logging
import sys
import time
from pathlib import Path

import pandas as pd

import config
from pipeline.compute_stats import compute_stats
from pipeline.fetch_ladder import fetch_ladder
from pipeline.fetch_match_ids import fetch_match_ids
from pipeline.fetch_matches import fetch_matches
from riot_client import RiotClient

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger(__name__)


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Fetch NA top-ladder LoL stats.")
    p.add_argument("--top", type=int, default=config.TOP_N_PLAYERS, help="Number of players")
    p.add_argument("--concurrency", type=int, default=config.MAX_CONCURRENCY, help="Max concurrent requests")
    p.add_argument("--no-parquet", action="store_true", help="Skip Parquet output")
    p.add_argument("--csv", action="store_true", help="Also write CSV alongside Parquet")
    return p.parse_args()


def _write_outputs(df: pd.DataFrame, no_parquet: bool, also_csv: bool) -> None:
    out_dir = config.OUTPUT_DIR

    if not no_parquet:
        parquet_path = out_dir / "na_top1000_stats.parquet"
        df.to_parquet(parquet_path, index=True)
        log.info("Parquet written → %s", parquet_path)

    if no_parquet or also_csv:
        csv_path = out_dir / "na_top1000_stats.csv"
        df.to_csv(csv_path, index=True)
        log.info("CSV written    → %s", csv_path)


async def run(args: argparse.Namespace) -> None:
    t0 = time.monotonic()

    # Override config values from CLI flags
    config.TOP_N_PLAYERS  = args.top
    config.MAX_CONCURRENCY = args.concurrency

    async with RiotClient(max_concurrency=args.concurrency) as client:

        # ── 1. Ladder ────────────────────────────────────────────────────────
        log.info("=" * 60)
        log.info("Phase 1/3 — Fetching ladder (top %d players)", args.top)
        ladder = await fetch_ladder(client, top_n=args.top)
        if not ladder:
            log.error("Ladder returned 0 entries. Check your API key.")
            sys.exit(1)

        # League-V4 now returns puuid directly in each entry.
        players = ladder

        # ── 2. Match IDs ─────────────────────────────────────────────────────
        log.info("=" * 60)
        log.info("Phase 2/3 — Fetching match ID lists")
        match_id_map = await fetch_match_ids(client, players)

        # ── 3. Match details ─────────────────────────────────────────────────
        log.info("=" * 60)
        log.info("Phase 3/3 — Downloading match details")
        await fetch_matches(client, match_id_map)

    # ── 5. Compute stats (CPU-only, no network) ───────────────────────────────
    log.info("=" * 60)
    log.info("Computing stats…")
    df = compute_stats(players, match_id_map)

    # ── 6. Write output ───────────────────────────────────────────────────────
    _write_outputs(df, no_parquet=args.no_parquet, also_csv=args.csv)

    elapsed = time.monotonic() - t0
    log.info("=" * 60)
    log.info("Done!  %d players processed in %.1f seconds.", len(df), elapsed)
    log.info("")
    log.info("Preview (top 10):")
    preview_cols = ["summoner_name", "rank_lp", "games_played", "kda", "kill_part_pct", "bloodiness"]
    print(df[preview_cols].head(10).to_string())


def main() -> None:
    args = _parse_args()
    asyncio.run(run(args))


if __name__ == "__main__":
    main()
