"""
Central configuration for the PlayerPotential Riot API scraper.

Copy .env.example to .env and set RIOT_API_KEY before running.
"""

import os
from pathlib import Path
from dotenv import load_dotenv

# ── Paths ────────────────────────────────────────────────────────────────────
BASE_DIR = Path(os.getenv("PLAYER_POTENTIAL_BASE_DIR", "/tmp/PlayerPotential"))
CACHE_DIR = BASE_DIR / "cache"
OUTPUT_DIR = BASE_DIR / "output"

# ── Region selection ──────────────────────────────────────────────────────────
# EUW routing: platform endpoints use euw1, Match-V5 uses europe.
PLATFORM_REGION: str = "euw1"
REGIONAL_ROUTING: str = "europe"
REGION_LABEL: str = "euw"

CACHE_REGION_DIR = CACHE_DIR / PLATFORM_REGION
CACHE_SUMMONERS_DIR = CACHE_REGION_DIR / "summoners"
CACHE_MATCH_IDS_DIR = CACHE_REGION_DIR / "match_ids"
CACHE_MATCHES_DIR   = CACHE_REGION_DIR / "matches"

for _d in (CACHE_SUMMONERS_DIR, CACHE_MATCH_IDS_DIR, CACHE_MATCHES_DIR, OUTPUT_DIR):
    os.makedirs(_d, exist_ok=True)

# ── API Key ───────────────────────────────────────────────────────────────────
def _resolve_riot_api_key() -> str:
    """Resolve RIOT_API_KEY from env var or one of several .env locations."""
    key = os.getenv("RIOT_API_KEY")
    if key:
        return key

    env_candidates: list[Path] = []
    env_override = os.getenv("PLAYER_POTENTIAL_ENV_FILE")
    if env_override:
        env_candidates.append(Path(env_override))

    env_candidates.extend(
        [
            BASE_DIR / ".env",
            Path.cwd() / ".env",
            Path(__file__).resolve().parent / ".env",
        ]
    )

    seen: set[Path] = set()
    for env_file in env_candidates:
        resolved = env_file.resolve()
        if resolved in seen:
            continue
        seen.add(resolved)

        if resolved.exists():
            load_dotenv(resolved, override=False)
            key = os.getenv("RIOT_API_KEY")
            if key:
                return key

    raise KeyError(
        "RIOT_API_KEY is not set. Set it as an environment variable, set PLAYER_POTENTIAL_ENV_FILE "
        "to a .env path, or place a .env file in one of: "
        f"{BASE_DIR / '.env'}, {Path.cwd() / '.env'}, {Path(__file__).resolve().parent / '.env'}."
    )


RIOT_API_KEY: str = _resolve_riot_api_key()

# ── Riot API hosts ────────────────────────────────────────────────────────────
PLATFORM_HOST  = f"https://{PLATFORM_REGION}.api.riotgames.com"   # League-V4, Summoner-V4
REGIONAL_HOST  = f"https://{REGIONAL_ROUTING}.api.riotgames.com"  # Match-V5

# ── Season / filter constants ─────────────────────────────────────────────────
# Season 2026 Split 1 start: January 8, 2026 00:00 UTC
SEASON_START_EPOCH: int = 1736294400

# Match-V5 queue ID for ranked solo/duo
RANKED_SOLO_QUEUE: int = 420

# How many players to fetch from the top of the ladder
TOP_N_PLAYERS: int = 1000

# ── HTTP / concurrency settings ───────────────────────────────────────────────
# Maximum simultaneous in-flight requests.
# With smoothed pacing at roughly 50 req/s, 30-60 is usually enough to hide
# network latency without creating unnecessary in-flight pressure.
MAX_CONCURRENCY: int = int(os.getenv("MAX_CONCURRENCY", "40"))

# App-level Riot limits for this key.
# Override via environment variables if your key changes.
APP_RATE_LIMIT_SHORT: int = int(os.getenv("APP_RATE_LIMIT_SHORT", "500"))
APP_RATE_LIMIT_SHORT_WINDOW_SEC: float = float(os.getenv("APP_RATE_LIMIT_SHORT_WINDOW_SEC", "10"))
APP_RATE_LIMIT_LONG: int = int(os.getenv("APP_RATE_LIMIT_LONG", "30000"))
APP_RATE_LIMIT_LONG_WINDOW_SEC: float = float(os.getenv("APP_RATE_LIMIT_LONG_WINDOW_SEC", "600"))

# Batch size for paginating match IDs per player
MATCH_ID_PAGE_SIZE: int = 100

# Maximum retries on 5xx errors (via tenacity)
MAX_RETRIES_5XX: int = 5
