import argparse
import json
import logging
from collections.abc import Generator, Iterable
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import polars as pl
from tqdm import tqdm


def _isoformat(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).isoformat(timespec="seconds")


def _game_status(
    game_dir: Path,
    *,
    min_gap: timedelta,
    gap_factor: float,
) -> dict[str, Any] | None:
    timestamps = (
        pl.scan_ipc(game_dir / "*.arrow", memory_map=False)
        .select("id", "timestamp")
        .unique("id")
        .select("timestamp")
        .sort("timestamp")
        .collect()
    )

    if timestamps.is_empty():
        return None

    # Quiet games naturally go a long time without matches, so a gap has to be
    # long relative to the game's average time between matches
    oldest: datetime = timestamps["timestamp"].min()  # type: ignore[assignment]
    newest: datetime = timestamps["timestamp"].max()  # type: ignore[assignment]
    mean_interval = (newest - oldest) / max(timestamps.height - 1, 1)
    gap_threshold = max(min_gap, gap_factor * mean_interval)

    gaps = (
        timestamps.with_columns(start=pl.col("timestamp").shift())
        .filter(pl.col("timestamp") - pl.col("start") > gap_threshold)
        .select("start", end="timestamp")
    )

    return {
        "num_matches": timestamps.height,
        "oldest": _isoformat(oldest),
        "newest": _isoformat(newest),
        "gaps": [
            {"start": _isoformat(start), "end": _isoformat(end)}
            for start, end in gaps.iter_rows()
        ],
    }


def _game_statuses(
    game_dirs: Iterable[Path],
    *,
    games: dict[int, dict[str, Any]],
    min_gap: timedelta,
    gap_factor: float,
) -> Generator[dict[str, Any]]:
    for game_dir in game_dirs:
        status = _game_status(game_dir, min_gap=min_gap, gap_factor=gap_factor)
        if status is None:
            continue

        game_id = int(game_dir.name)
        game = games.get(game_id) or {}
        games_played = game.get("games_played")
        yield {
            **status,
            "game_id": game_id,
            "name": game.get("display_name_en"),
            "games_played": games_played,
            "coverage": status["num_matches"] / games_played if games_played else None,
        }


def scrape_status(
    *,
    partitions_dir: Path | str,
    games_path: Path | str,
    output_path: Path | str,
    min_gap: timedelta = timedelta(hours=6),
    gap_factor: float = 100,
    progress_bar: bool = False,
) -> None:
    """Summarise per game which matches have been scraped so far. A gap is a
    period without matches longer than both `min_gap` and `gap_factor` times
    the game's average time between matches."""

    partitions_dir = Path(partitions_dir).resolve()
    games_path = Path(games_path).resolve()
    output_path = Path(output_path).resolve()

    games = {
        row["id"]: row
        for row in pl.read_ndjson(games_path)
        .select("id", "display_name_en", "games_played")
        .iter_rows(named=True)
    }

    game_dirs = sorted(
        (d for d in partitions_dir.iterdir() if d.is_dir() and d.name.isdigit()),
        key=lambda d: int(d.name),
    )
    logging.info(
        "Summarising scrape status of %d games in <%s>",
        len(game_dirs),
        partitions_dir,
    )

    statuses = _game_statuses(
        tqdm(game_dirs) if progress_bar else game_dirs,
        games=games,
        min_gap=min_gap,
        gap_factor=gap_factor,
    )

    result = {
        "generated_at": _isoformat(datetime.now(timezone.utc)),
        "gap_factor": gap_factor,
        "min_gap_hours": min_gap.total_seconds() / 3600,
        "games": list(statuses),
    }

    logging.info("Writing scrape status to <%s>", output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w") as file:
        json.dump(result, file, sort_keys=True, indent=4)
        file.write("\n")


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Summarise per game which matches have been scraped so far.",
    )
    parser.add_argument(
        "--partitions-dir",
        type=str,
        default="results/arrow/partitions",
        help="Directory with the match partitions, one subdirectory per game.",
    )
    parser.add_argument(
        "--games-path",
        type=str,
        default="csv/games.jl",
        help="Path to the merged games JL file.",
    )
    parser.add_argument(
        "--output-path",
        type=str,
        default="csv/scrape_status.json",
        help="Path to save the scrape status JSON file.",
    )
    parser.add_argument(
        "--progress-bar",
        "-p",
        action="store_true",
        help="Show a progress bar while summarising games.",
    )
    return parser.parse_args()


def main() -> None:
    args = _parse_args()
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(processName)s] %(levelname)s: %(message)s",
    )
    scrape_status(
        partitions_dir=args.partitions_dir,
        games_path=args.games_path,
        output_path=args.output_path,
        progress_bar=args.progress_bar,
    )


if __name__ == "__main__":
    main()
