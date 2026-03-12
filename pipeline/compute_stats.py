"""
Aggregates per-player stats from cached match JSON files.

Stats computed per player
─────────────────────────
rank_lp         str     e.g. "CHALLENGER I — 1234 LP"
games_played    int     wins + losses from the league entry
kda             float   (ΣKills + ΣAssists) / max(ΣDeaths, 1)
kill_part_pct   float   mean of (kills+assists)/max(team_kills,1) per game × 100
bloodiness      float   Σ(all-participant kills per game) / Σ(game_duration_min)

Notes on bloodiness
────────────────────
"Bloodiness" is a game-level metric: how kill-heavy are the games this player
participates in?  For each match we sum every participant's kills (all 10 players)
then divide total kills by total game minutes across all matches.
"""

import logging
from typing import Any

import pandas as pd

from pipeline.fetch_matches import load_match

log = logging.getLogger(__name__)


def _rank_lp_label(entry: dict[str, Any]) -> str:
    tier = entry["tier"]          # e.g. CHALLENGER
    rank = entry["rank"]          # e.g. I
    lp   = entry["leaguePoints"]
    return f"{tier} {rank} — {lp} LP"


def compute_stats(
    players: list[dict[str, Any]],
    match_id_map: dict[str, list[str]],
) -> pd.DataFrame:
    """
    Build a DataFrame with one row per player containing all requested stats.
    """
    rows: list[dict[str, Any]] = []

    for player in players:
        puuid      = player["puuid"]
        match_ids  = match_id_map.get(puuid, [])

        # Accumulators
        total_kills     = 0
        total_deaths    = 0
        total_assists   = 0
        sum_game_kills  = 0     # all 10 participants' kills per game, summed
        sum_game_min    = 0.0   # total minutes played across games
        kp_values: list[float] = []   # per-game KP ratios

        games_with_data = 0

        for mid in match_ids:
            match = load_match(mid)
            if match is None:
                log.warning("Missing cache for match %s — skipping.", mid)
                continue

            info = match.get("info", {})
            duration_sec: int = info.get("gameDuration", 0)
            if duration_sec < 180:
                # Skip remakes (< 3 minutes)
                continue

            duration_min = duration_sec / 60.0
            participants: list[dict] = info.get("participants", [])

            # Find this player's participant entry
            player_part = next(
                (p for p in participants if p.get("puuid") == puuid), None
            )
            if player_part is None:
                continue

            games_with_data += 1

            p_kills   = player_part.get("kills", 0)
            p_deaths  = player_part.get("deaths", 0)
            p_assists = player_part.get("assists", 0)

            total_kills   += p_kills
            total_deaths  += p_deaths
            total_assists += p_assists

            # Bloodiness: sum ALL participants' kills for this game
            game_total_kills = sum(p.get("kills", 0) for p in participants)
            sum_game_kills += game_total_kills
            sum_game_min   += duration_min

            # KP: per-game, based on player's team
            player_team_id = player_part.get("teamId")
            team_kills = sum(
                p.get("kills", 0)
                for p in participants
                if p.get("teamId") == player_team_id
            )
            kp = (p_kills + p_assists) / max(team_kills, 1)
            kp_values.append(kp)

        kda = (total_kills + total_assists) / max(total_deaths, 1)
        bloodiness = sum_game_kills / sum_game_min if sum_game_min > 0 else 0.0
        kill_part_pct = (sum(kp_values) / len(kp_values) * 100) if kp_values else 0.0

        rows.append(
            {
                "summoner_name":   player.get("summonerName", ""),
                "puuid":           puuid,
                "rank_lp":         _rank_lp_label(player),
                "tier":            player["tier"],
                "rank":            player["rank"],
                "league_points":   player["leaguePoints"],
                "games_played":    player["wins"] + player["losses"],
                "kda":             round(kda, 3),
                "kill_part_pct":   round(kill_part_pct, 2),
                "bloodiness":      round(bloodiness, 3),
                "games_with_data": games_with_data,
            }
        )

    df = pd.DataFrame(rows)
    # Sort by LP descending (preserves original ladder rank)
    df.sort_values("league_points", ascending=False, inplace=True)
    df.reset_index(drop=True, inplace=True)
    df.index += 1  # 1-based rank
    df.index.name = "ladder_rank"
    return df
