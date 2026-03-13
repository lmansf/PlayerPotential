
# PlayerPotential

PlayerPotential is an asynchronous Riot API data pipeline for League of Legends.
It targets top ranked Solo/Duo players (currently EUW by default), collects match
history and match detail data, then computes player-level metrics such as KDA,
kill participation, and game bloodiness.

The project is built for repeat runs: API responses are cached on disk, so
subsequent runs only request missing data.

## Features

- Fetch top N ladder players from Challenger, Grandmaster, and Master
- Pull paginated ranked Solo/Duo match IDs since a configurable season start
- Download and cache unique match payloads with resumable behavior
- Enforce Riot app-level rate limits with dual-window throttling
- Retry on transient failures (429 and 5xx)
- Compute aggregate player metrics into a tabular dataset
- Export Parquet (default) and optional CSV

## How The Pipeline Works

Execution starts in `main.py` and runs in this order:

1. Ladder fetch (`pipeline/fetch_ladder.py`)
2. Match ID fetch (`pipeline/fetch_match_ids.py`)
3. Match detail fetch (`pipeline/fetch_matches.py`)
4. Stats compute (`pipeline/compute_stats.py`)
5. Dataset write to `output/`

The HTTP client in `riot_client.py` manages concurrency, pacing, and retry logic.

## Project Structure

```
PlayerPotential/
	config.py
	main.py
	riot_client.py
	requirements.txt
	README.md
	pipeline/
		compute_stats.py
		fetch_ladder.py
		fetch_match_ids.py
		fetch_matches.py
		fetch_summoners.py
	cache/
		<platform_region>/
			summoners/
			match_ids/
			matches/
	output/
```

Notes:
- `fetch_summoners.py` is a legacy resolver path and is not required in the
	current main flow because League V4 ladder entries already include `puuid`.
- Cache and output directories are created automatically.

## Requirements

- Python 3.10+
- A Riot API key

Install dependencies:

```bash
pip install -r requirements.txt
```

## Configuration

Configuration is centralized in `config.py`.

### 1) Environment Variables

Create a `.env` file in the project root:

```env
RIOT_API_KEY=RGAPI-your-key-here

# Optional tuning
MAX_CONCURRENCY=40
APP_RATE_LIMIT_SHORT=500
APP_RATE_LIMIT_SHORT_WINDOW_SEC=10
APP_RATE_LIMIT_LONG=30000
APP_RATE_LIMIT_LONG_WINDOW_SEC=600
```

Required:
- `RIOT_API_KEY`

Optional:
- `MAX_CONCURRENCY`: upper bound for in-flight requests
- App rate-limit values if your key has different limits

### 2) Region And Routing

Set these in `config.py`:

- `PLATFORM_REGION` (example: `euw1`)
- `REGIONAL_ROUTING` (example: `europe`)
- `REGION_LABEL` (example: `euw`)

These values control:
- API hosts (`PLATFORM_HOST`, `REGIONAL_HOST`)
- Region-scoped cache path (`cache/<platform_region>/...`)
- Output filename prefix (`<region>_top<top>_stats.*`)

### 3) Season Start

`SEASON_START_EPOCH` controls how far back match-id collection goes. Update this
for new splits/seasons.

## Usage

Default run:

```bash
python main.py
```

Example runs:

```bash
# Smaller sample
python main.py --top 300

# Lower request pressure
python main.py --concurrency 25 --batch-size 1500

# CSV output in addition to Parquet
python main.py --csv

# CSV only
python main.py --no-parquet
```

### CLI Arguments

- `--top N`: number of ladder players to include (default from `config.TOP_N_PLAYERS`)
- `--concurrency N`: max concurrent requests (default from `config.MAX_CONCURRENCY`)
- `--batch-size N`: fetch match details in chunks (0 means single pass)
- `--no-parquet`: skip Parquet output
- `--csv`: also write CSV

## Output

Output files are written to `output/`:

- Parquet (default): `<region>_top<top>_stats.parquet`
- CSV (optional): `<region>_top<top>_stats.csv`

The computed table includes:

| Column | Description |
| --- | --- |
| `ladder_rank` (index) | 1-based rank after sorting by league points |
| `summoner_name` | Riot ID display name from ladder data |
| `puuid` | Global player UUID |
| `rank_lp` | Tier/rank/LP label |
| `tier` | Ladder tier |
| `rank` | Division |
| `league_points` | LP value |
| `games_played` | `wins + losses` from ladder snapshot |
| `kda` | `(kills + assists) / max(deaths, 1)` across parsed matches |
| `kill_part_pct` | Mean per-game kill participation percentage |
| `bloodiness` | Total game kills across participants per game-minute |
| `games_with_data` | Number of usable cached matches for that player |

## Caching Behavior

Caching is region-scoped and designed for resumable runs:

- Match IDs: `cache/<platform_region>/match_ids/<puuid>.json`
- Match details: `cache/<platform_region>/matches/<match_id>.json`
- Summoner lookups (legacy path): `cache/<platform_region>/summoners/<summoner_id>.json`

If cached files exist, they are reused.

To force re-fetch:
- Delete specific cache subfolders, or
- Delete the full `cache/<platform_region>/` directory

## Rate Limiting And Reliability

`riot_client.py` applies:

- Async semaphore for max in-flight requests
- Dual-window request pacing
- 429 handling via `Retry-After`
- Exponential backoff for 5xx errors

This makes long runs more stable and helps avoid aggressive burst patterns.

## Performance Notes

- Start with lower `--concurrency` on laptops if you see heavy resource usage.
- Use `--batch-size` to process match fetches in chunks and reduce sustained load.
- Parquet output requires `pyarrow` (already in `requirements.txt`).

## Troubleshooting

- `KeyError: 'RIOT_API_KEY'`
	- Add `RIOT_API_KEY` to `.env` in project root.

- `HTTP 403` on Riot endpoints
	- Your key may be invalid or expired.

- Frequent 429 responses
	- Lower `--concurrency` and check app limit env vars.

- Empty ladder result
	- Verify region constants in `config.py` and key scope.

- Missing or partial match data after interruption
	- Re-run the same command; cache-aware fetchers resume missing data.

## Reference Link

Resource for later:

https://streamscharts.com/channels?game=league-of-legends&lang=en