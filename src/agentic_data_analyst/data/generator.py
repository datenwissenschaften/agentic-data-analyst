"""Generate deterministic, relational gaming analytics Parquet datasets."""

from __future__ import annotations

import argparse
import json
import random
import shutil
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pyarrow as pa
import pyarrow.parquet as pq

SEED = 20_250_601
ANCHOR = datetime(2025, 6, 1, tzinfo=UTC)
DATASET_NAMES = ("players", "sessions", "matches", "events", "purchases")

SCHEMAS = {
    "players": pa.schema(
        [
            pa.field("player_id", pa.string(), nullable=False),
            pa.field("signup_at", pa.timestamp("us", tz="UTC"), nullable=False),
            pa.field("segment", pa.string(), nullable=False),
            pa.field("region", pa.string(), nullable=False),
            pa.field("acquisition_channel", pa.string(), nullable=False),
        ]
    ),
    "sessions": pa.schema(
        [
            pa.field("session_id", pa.string(), nullable=False),
            pa.field("player_id", pa.string(), nullable=False),
            pa.field("session_start", pa.timestamp("us", tz="UTC"), nullable=False),
            pa.field("session_end", pa.timestamp("us", tz="UTC"), nullable=False),
            pa.field("duration_minutes", pa.float64(), nullable=False),
            pa.field("device", pa.string(), nullable=False),
        ]
    ),
    "matches": pa.schema(
        [
            pa.field("match_id", pa.string(), nullable=False),
            pa.field("player_id", pa.string(), nullable=False),
            pa.field("match_start", pa.timestamp("us", tz="UTC"), nullable=False),
            pa.field("mode", pa.string(), nullable=False),
            pa.field("outcome", pa.string(), nullable=False),
            pa.field("score", pa.int64(), nullable=False),
        ]
    ),
    "events": pa.schema(
        [
            pa.field("event_id", pa.string(), nullable=False),
            pa.field("player_id", pa.string(), nullable=False),
            pa.field("session_id", pa.string(), nullable=False),
            pa.field("event_time", pa.timestamp("us", tz="UTC"), nullable=False),
            pa.field("event_type", pa.string(), nullable=False),
        ]
    ),
    "purchases": pa.schema(
        [
            pa.field("purchase_id", pa.string(), nullable=False),
            pa.field("player_id", pa.string(), nullable=False),
            pa.field("purchased_at", pa.timestamp("us", tz="UTC"), nullable=False),
            pa.field("product_type", pa.string(), nullable=False),
            pa.field("amount", pa.float64(), nullable=False),
            pa.field("currency", pa.string(), nullable=False),
        ]
    ),
}

METADATA: dict[str, dict[str, Any]] = {
    "players": {
        "description": "Player account, acquisition, geography, and behavioral segment attributes.",
        "tags": ["player", "segment", "retention", "churn", "acquisition"],
        "columns": {
            "player_id": {"description": "Stable synthetic player identifier."},
            "signup_at": {"description": "UTC account creation time."},
            "segment": {"description": "Behavioral segment assigned at signup."},
            "region": {"description": "Synthetic player region."},
            "acquisition_channel": {"description": "Channel credited with acquisition."},
        },
    },
    "sessions": {
        "description": "Player login sessions with duration and device context.",
        "tags": ["session", "engagement", "retention", "churn", "duration"],
        "columns": {
            "session_id": {"description": "Stable synthetic session identifier."},
            "player_id": {"description": "Player that opened the session."},
            "session_start": {"description": "UTC session start time."},
            "session_end": {"description": "UTC session end time."},
            "duration_minutes": {"description": "Session length in minutes."},
            "device": {"description": "Device family used for the session."},
        },
        "relationships": [
            {
                "source_column": "player_id",
                "target_dataset": "players",
                "target_column": "player_id",
                "relationship": "many_to_one",
            }
        ],
    },
    "matches": {
        "description": "Completed multiplayer matches and player outcomes.",
        "tags": ["match", "gameplay", "engagement", "score"],
        "columns": {
            "match_id": {"description": "Stable synthetic match participation identifier."},
            "player_id": {"description": "Player represented by this match row."},
            "match_start": {"description": "UTC match start time."},
            "mode": {"description": "Game mode."},
            "outcome": {"description": "Win, loss, or draw."},
            "score": {"description": "Points earned during the match."},
        },
        "relationships": [
            {
                "source_column": "player_id",
                "target_dataset": "players",
                "target_column": "player_id",
                "relationship": "many_to_one",
            }
        ],
    },
    "events": {
        "description": "Product telemetry events emitted during player sessions.",
        "tags": ["event", "funnel", "feature", "engagement"],
        "columns": {
            "event_id": {"description": "Stable synthetic event identifier."},
            "player_id": {"description": "Player that emitted the event."},
            "session_id": {"description": "Session containing the event."},
            "event_time": {"description": "UTC event time."},
            "event_type": {"description": "Normalized product event name."},
        },
        "relationships": [
            {
                "source_column": "player_id",
                "target_dataset": "players",
                "target_column": "player_id",
                "relationship": "many_to_one",
            },
            {
                "source_column": "session_id",
                "target_dataset": "sessions",
                "target_column": "session_id",
                "relationship": "many_to_one",
            },
        ],
    },
    "purchases": {
        "description": "Successful in-game purchases with product and revenue attributes.",
        "tags": ["purchase", "conversion", "revenue", "monetization"],
        "columns": {
            "purchase_id": {"description": "Stable synthetic purchase identifier."},
            "player_id": {"description": "Player that made the purchase."},
            "purchased_at": {"description": "UTC purchase time."},
            "product_type": {"description": "Purchased virtual product category."},
            "amount": {"description": "Gross synthetic purchase amount in USD."},
            "currency": {"description": "ISO currency code; USD in sample data."},
        },
        "relationships": [
            {
                "source_column": "player_id",
                "target_dataset": "players",
                "target_column": "player_id",
                "relationship": "many_to_one",
            }
        ],
    },
}


def generate(output_dir: Path, *, player_count: int = 240, seed: int = SEED, force: bool = False) -> None:
    """Write a reproducible data snapshot and catalog annotations."""
    if player_count < 1:
        raise ValueError("player_count must be greater than zero")
    output_dir.mkdir(parents=True, exist_ok=True)
    existing = [output_dir / f"{name}.parquet" for name in DATASET_NAMES]
    if any(path.exists() for path in existing) and not force:
        raise FileExistsError("Sample data already exists; pass --force to replace it")
    for path in existing:
        if path.is_dir():
            shutil.rmtree(path)
        elif path.exists():
            path.unlink()

    tables = _build_rows(player_count=player_count, seed=seed)
    for name, rows in tables.items():
        pq.write_table(
            pa.Table.from_pylist(rows, schema=SCHEMAS[name]),
            output_dir / f"{name}.parquet",
            compression="snappy",
        )
        metadata_path = output_dir / f"{name}.metadata.json"
        metadata_path.write_text(json.dumps(METADATA[name], indent=2) + "\n", encoding="utf-8")


def _build_rows(*, player_count: int, seed: int) -> dict[str, list[dict[str, Any]]]:
    rng = random.Random(seed)
    players: list[dict[str, Any]] = []
    sessions: list[dict[str, Any]] = []
    matches: list[dict[str, Any]] = []
    events: list[dict[str, Any]] = []
    purchases: list[dict[str, Any]] = []
    segment_profiles = {
        "casual": (8, 0.90, 0.05),
        "core": (22, 0.97, 0.16),
        "competitive": (35, 0.985, 0.28),
    }
    session_number = match_number = event_number = purchase_number = 0

    for index in range(player_count):
        player_id = f"player_{index:05d}"
        segment = rng.choices(["casual", "core", "competitive"], weights=[50, 35, 15])[0]
        signup = ANCHOR - timedelta(days=rng.randint(30, 150), hours=rng.randint(0, 23))
        players.append(
            {
                "player_id": player_id,
                "signup_at": signup,
                "segment": segment,
                "region": rng.choice(["NA", "EU", "APAC", "LATAM"]),
                "acquisition_channel": rng.choice(["organic", "paid_search", "creator", "referral"]),
            }
        )
        expected_sessions, survival, purchase_rate = segment_profiles[segment]
        cursor = signup + timedelta(hours=rng.randint(0, 12))
        target_sessions = max(1, round(rng.gauss(expected_sessions, expected_sessions / 3)))
        for session_index in range(target_sessions):
            if session_index > 1 and rng.random() > survival ** (session_index / 4):
                break
            session_number += 1
            session_id = f"session_{session_number:07d}"
            cursor += timedelta(hours=rng.uniform(8, 72))
            if cursor > ANCHOR:
                break
            duration = max(2, round(rng.lognormvariate(2.7 if segment == "casual" else 3.3, 0.5), 1))
            session_end = cursor + timedelta(minutes=duration)
            sessions.append(
                {
                    "session_id": session_id,
                    "player_id": player_id,
                    "session_start": cursor,
                    "session_end": session_end,
                    "duration_minutes": duration,
                    "device": rng.choice(["desktop", "console", "mobile"]),
                }
            )
            event_types = ["session_start", "menu_open", "match_queue", "store_view"]
            for event_type in rng.sample(event_types, k=rng.randint(2, len(event_types))):
                event_number += 1
                events.append(
                    {
                        "event_id": f"event_{event_number:08d}",
                        "player_id": player_id,
                        "session_id": session_id,
                        "event_time": cursor + timedelta(minutes=rng.uniform(0, duration)),
                        "event_type": event_type,
                    }
                )
            for _ in range(rng.randint(0, 3 if segment != "casual" else 1)):
                match_number += 1
                matches.append(
                    {
                        "match_id": f"match_{match_number:08d}",
                        "player_id": player_id,
                        "match_start": cursor + timedelta(minutes=rng.uniform(1, duration)),
                        "mode": rng.choice(["ranked", "casual", "co_op"]),
                        "outcome": rng.choices(["win", "loss", "draw"], weights=[45, 45, 10])[0],
                        "score": max(0, round(rng.gauss(1_000, 350))),
                    }
                )
            if rng.random() < purchase_rate:
                purchase_number += 1
                purchases.append(
                    {
                        "purchase_id": f"purchase_{purchase_number:07d}",
                        "player_id": player_id,
                        "purchased_at": cursor + timedelta(minutes=rng.uniform(1, duration)),
                        "product_type": rng.choice(["cosmetic", "currency", "season_pass"]),
                        "amount": rng.choice([2.99, 4.99, 9.99, 19.99]),
                        "currency": "USD",
                    }
                )
    return {
        "players": players,
        "sessions": sessions,
        "matches": matches,
        "events": events,
        "purchases": purchases,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=Path("data/sample"))
    parser.add_argument("--players", type=int, default=240)
    parser.add_argument("--seed", type=int, default=SEED)
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()
    generate(args.output, player_count=args.players, seed=args.seed, force=args.force)


if __name__ == "__main__":
    main()
