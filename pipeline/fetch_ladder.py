"""
Fetches the top-N players from the NA ranked solo/duo ladder.

Pulls Challenger → Grandmaster → Master (in that order) and merges the lists,
sorted by leaguePoints descending, returning the top TOP_N_PLAYERS entries.

Each returned dict has:
    puuid        str   (directly from league entry — no extra API call needed)
    summoner_name str  "GameName#TAG"
    tier         str   (CHALLENGER / GRANDMASTER / MASTER)
    rank         str   (I / II / III / IV — always I for Chall/GM)
    leaguePoints int
    wins         int
    losses       int
"""

import logging
from typing import Any

import config
from riot_client import RiotClient

log = logging.getLogger(__name__)

_TIERS = [
    ("CHALLENGER",   f"{config.PLATFORM_HOST}/lol/league/v4/challengerleagues/by-queue/RANKED_SOLO_5x5"),
    ("GRANDMASTER",  f"{config.PLATFORM_HOST}/lol/league/v4/grandmasterleagues/by-queue/RANKED_SOLO_5x5"),
    ("MASTER",       f"{config.PLATFORM_HOST}/lol/league/v4/masterleagues/by-queue/RANKED_SOLO_5x5"),
]


async def fetch_ladder(client: RiotClient, top_n: int | None = None) -> list[dict[str, Any]]:
    """Return the top-N ladder entries sorted by LP descending."""
    target_n = top_n or config.TOP_N_PLAYERS
    all_entries: list[dict[str, Any]] = []

    for tier_name, url in _TIERS:
        if len(all_entries) >= target_n:
            break

        log.info("Fetching %s league…", tier_name)
        data = await client.get(url)

        for entry in data.get("entries", []):
            game_name = entry.get("riotIdGameName", "")
            tag_line  = entry.get("riotIdTagline", "")
            name = f"{game_name}#{tag_line}" if game_name else ""
            all_entries.append(
                {
                    "puuid":        entry["puuid"],
                    "summonerName": name,
                    "tier":         tier_name,
                    "rank":         entry.get("rank", "I"),
                    "leaguePoints": entry["leaguePoints"],
                    "wins":         entry["wins"],
                    "losses":       entry["losses"],
                }
            )

        log.info("  → %d entries so far (including new %s entries)", len(all_entries), tier_name)

    # Sort all entries by LP descending, then take top N
    all_entries.sort(key=lambda e: e["leaguePoints"], reverse=True)
    top = all_entries[:target_n]

    log.info("Ladder fetch complete — %d players selected.", len(top))
    return top
