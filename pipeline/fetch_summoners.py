"""
Resolves summonerId → puuid for each ladder entry.

Results are cached under cache/<platform_region>/summoners/{summonerId}.json
so that re-runs only hit the API for new players.
"""

import asyncio
import json
import logging
from typing import Any

from tqdm.asyncio import tqdm

from config import CACHE_SUMMONERS_DIR, PLATFORM_HOST
from riot_client import RiotClient

log = logging.getLogger(__name__)


async def _fetch_one(
    client: RiotClient,
    entry: dict[str, Any],
) -> dict[str, Any]:
    """Fetch (or load from cache) summoner data for one entry; returns entry with 'puuid' added."""
    summoner_id = entry["summonerId"]
    cache_file = CACHE_SUMMONERS_DIR / f"{summoner_id}.json"

    if cache_file.exists():
        data = json.loads(cache_file.read_text(encoding="utf-8"))
    else:
        url = f"{PLATFORM_HOST}/lol/summoner/v4/summoners/{summoner_id}"
        data = await client.get(url)
        cache_file.write_text(json.dumps(data), encoding="utf-8")

    return {**entry, "puuid": data["puuid"]}


async def fetch_summoners(
    client: RiotClient,
    ladder: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """
    Resolve PUUIDs for all ladder entries.

    Returns a new list of entry dicts, each augmented with a 'puuid' key.
    """
    log.info("Resolving PUUIDs for %d players…", len(ladder))

    tasks = [_fetch_one(client, entry) for entry in ladder]
    results: list[dict[str, Any]] = []

    for coro in tqdm(
        asyncio.as_completed(tasks),
        total=len(tasks),
        desc="Fetching PUUIDs",
        unit="player",
    ):
        results.append(await coro)

    log.info("PUUID resolution complete.")
    # Preserve original ladder order (as_completed doesn't)
    order = {e["summonerId"]: i for i, e in enumerate(ladder)}
    results.sort(key=lambda e: order[e["summonerId"]])
    return results
