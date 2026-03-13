"""
Downloads match detail JSON for every unique match ID collected across all players.

Each match is cached under cache/<platform_region>/matches/{matchId}.json.
Already-cached files are skipped, so re-runs (or runs after interruption)
only fetch new matches.
"""

import asyncio
import json
import logging
from typing import Any

from tqdm.asyncio import tqdm

from config import CACHE_MATCHES_DIR, MAX_CONCURRENCY, REGIONAL_HOST
from riot_client import RiotClient

log = logging.getLogger(__name__)

_MATCH_URL = f"{REGIONAL_HOST}/lol/match/v5/matches/{{match_id}}"


async def _fetch_one(client: RiotClient, match_id: str) -> None:
    """Download (or skip if cached) a single match."""
    cache_file = CACHE_MATCHES_DIR / f"{match_id}.json"
    if cache_file.exists():
        return

    url = _MATCH_URL.format(match_id=match_id)
    data = await client.get(url)
    cache_file.write_text(json.dumps(data), encoding="utf-8")


async def _fetch_batch(client: RiotClient, batch: list[str]) -> None:
    """Run the worker pool over a single batch of match IDs."""
    queue: asyncio.Queue[str | None] = asyncio.Queue()
    for mid in batch:
        queue.put_nowait(mid)

    worker_count = min(max(8, MAX_CONCURRENCY), len(batch))
    errors: list[Exception] = []
    progress = tqdm(total=len(batch), desc="Fetching matches", unit="match")

    async def worker() -> None:
        while True:
            match_id = await queue.get()
            if match_id is None:
                queue.task_done()
                return

            try:
                await _fetch_one(client, match_id)
            except Exception as exc:  # noqa: BLE001
                errors.append(exc)
            finally:
                progress.update(1)
                queue.task_done()

    workers = [asyncio.create_task(worker()) for _ in range(worker_count)]
    await queue.join()

    for _ in workers:
        queue.put_nowait(None)
    await asyncio.gather(*workers)
    progress.close()

    if errors:
        raise RuntimeError(f"Failed to fetch {len(errors)} matches; first error: {errors[0]}")


async def fetch_matches(
    client: RiotClient,
    match_id_map: dict[str, list[str]],
    batch_size: int = 0,
) -> None:
    """
    Download all unique matches referenced in match_id_map.

    After this function returns, every matchId in match_id_map has a
    corresponding file in the configured match-cache directory.

    Args:
        batch_size: If > 0, process uncached matches in chunks of this size,
                    logging progress between batches.  Useful on laptops to
                    limit sustained network/CPU load.  0 (default) fetches
                    everything in a single pass.
    """
    # Deduplicate across players (a single game has 10 participants)
    unique_ids: list[str] = list({mid for ids in match_id_map.values() for mid in ids})
    uncached_ids = [mid for mid in unique_ids if not (CACHE_MATCHES_DIR / f"{mid}.json").exists()]

    log.info(
        "Fetching %d uncached matches (from %d unique / %d total references)…",
        len(uncached_ids),
        len(unique_ids),
        sum(len(v) for v in match_id_map.values()),
    )
    if not uncached_ids:
        log.info("Match fetch complete (all matches already cached).")
        return

    if batch_size > 0:
        batches = [uncached_ids[i : i + batch_size] for i in range(0, len(uncached_ids), batch_size)]
    else:
        batches = [uncached_ids]

    for batch_num, batch in enumerate(batches, 1):
        if len(batches) > 1:
            log.info("Batch %d/%d — %d matches…", batch_num, len(batches), len(batch))
        await _fetch_batch(client, batch)

    log.info("Match fetch complete.")


def load_match(match_id: str) -> dict[str, Any] | None:
    """
    Load a cached match from disk.  Returns None if the file is missing
    (shouldn't happen after fetch_matches, but guards against partial runs).
    """
    cache_file = CACHE_MATCHES_DIR / f"{match_id}.json"
    if not cache_file.exists():
        return None
    return json.loads(cache_file.read_text(encoding="utf-8"))
