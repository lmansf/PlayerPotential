"""
Fetches the full list of ranked solo match IDs for each player since the
current season start, using paginated calls to Match-V5.

Results are cached under cache/<platform_region>/match_ids/{puuid}.json,
so re-runs skip players already cached for the configured platform.
"""

import json
import logging
from typing import Any

from tqdm.asyncio import tqdm

from config import (
    CACHE_MATCH_IDS_DIR,
    MATCH_ID_PAGE_SIZE,
    RANKED_SOLO_QUEUE,
    REGIONAL_HOST,
    SEASON_START_EPOCH,
)
from riot_client import RiotClient

log = logging.getLogger(__name__)

_MATCH_IDS_URL = f"{REGIONAL_HOST}/lol/match/v5/matches/by-puuid/{{puuid}}/ids"


async def _fetch_ids_for_player(client: RiotClient, puuid: str) -> list[str]:
    """
    Return all ranked-solo match IDs for `puuid` since SEASON_START_EPOCH.
    Uses pagination (start offset + count) until a page returns fewer items
    than MATCH_ID_PAGE_SIZE.
    """
    cache_file = CACHE_MATCH_IDS_DIR / f"{puuid}.json"
    if cache_file.exists():
        return json.loads(cache_file.read_text(encoding="utf-8"))

    url = _MATCH_IDS_URL.format(puuid=puuid)
    all_ids: list[str] = []
    start = 0

    while True:
        page: list[str] = await client.get(
            url,
            queue=RANKED_SOLO_QUEUE,
            type="ranked",
            start=start,
            count=MATCH_ID_PAGE_SIZE,
            startTime=SEASON_START_EPOCH,
        )
        all_ids.extend(page)
        if len(page) < MATCH_ID_PAGE_SIZE:
            break
        start += MATCH_ID_PAGE_SIZE

    cache_file.write_text(json.dumps(all_ids), encoding="utf-8")
    return all_ids


async def fetch_match_ids(
    client: RiotClient,
    players: list[dict[str, Any]],
) -> dict[str, list[str]]:
    """
    Return a mapping of puuid → list[matchId] for all players.
    Also updates each player dict in-place with a 'match_ids' key.
    """
    log.info("Fetching match ID lists for %d players…", len(players))

    puuids = [p["puuid"] for p in players]
    tasks = [_fetch_ids_for_player(client, puuid) for puuid in puuids]
    match_id_map: dict[str, list[str]] = {}

    raw_results = await tqdm.gather(
        *tasks,
        desc="Fetching match IDs",
        unit="player",
    )

    total_matches = 0
    for puuid, ids in zip(puuids, raw_results):
        match_id_map[puuid] = ids
        total_matches += len(ids)

    log.info("Match ID fetch complete — %d unique calls, %d total match IDs.", len(puuids), total_matches)
    return match_id_map
