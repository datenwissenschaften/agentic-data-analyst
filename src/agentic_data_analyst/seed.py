"""Deterministic synthetic speedrun database: humans and AI agents racing fictional retro games.

Usage: `python -m agentic_data_analyst.seed data/speedruns.duckdb` (`make data`).

Every name and number is invented. The shape follows a real use case: human real-time runs next to AI agents
(tool-assisted search, reinforcement learning, LLM agents) that improve over months, with per-level splits.
Descriptions and keys are stored in the database itself (COMMENT ON, PRIMARY/FOREIGN KEY), so the schema documents
itself for the analyst.
"""

import random
import sys
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path

import duckdb
import pandas as pd

START = datetime(2025, 1, 1)
DAYS = 638  # until 2026-09-30


@dataclass(frozen=True)
class GameSpec:
    title: str
    platform: str
    release_year: int
    frame_rate: float
    levels: tuple[str, ...]
    # Category name -> time a strong human needs, in seconds.
    categories: dict[str, float]


GAMES = (
    GameSpec(
        "Serpent Scramble",
        "NES",
        1990,
        60.0988,
        ("Garden Gate", "Plateau", "Island Hop", "Scale Climb", "Bell Tower", "Rim Walk", "Gap Jump", "Summit Door"),
        {"Any%": 540.0, "Warpless": 610.0},
    ),
    GameSpec(
        "Pixel Plumber Panic",
        "NES",
        1986,
        60.0988,
        ("Pipe Works", "Brick Alley", "Cloud Steps", "Lava Run", "Fortress"),
        {"Any%": 295.0, "100%": 1180.0},
    ),
    GameSpec(
        "Turbo Comet",
        "Genesis",
        1991,
        59.9227,
        ("Launch Bay", "Asteroid Belt", "Nebula", "Ion Storm", "Mothership"),
        {"Any%": 1460.0},
    ),
    GameSpec(
        "Castle Quest Deluxe",
        "SNES",
        1992,
        60.0988,
        ("Moat", "Courtyard", "Library", "Crypt", "Clock Tower", "Throne Room", "Sky Keep"),
        {"Any%": 2350.0, "All Bosses": 3020.0},
    ),
    GameSpec(
        "Moonlit Maze",
        "Game Boy",
        1993,
        59.7275,
        ("Hedge", "Fountain", "Catacombs", "Observatory", "Crater", "Dark Side"),
        {"Any%": 880.0},
    ),
)


@dataclass(frozen=True)
class AgentSpec:
    handle: str
    method: str
    # Pace relative to a strong human at the first and at the latest run (lower is faster).
    first_pace: float
    final_pace: float
    reset_rate: float
    dnf_rate: float
    inputs_per_second: tuple[float, float]
    compute_hours: tuple[float, float]
    first_day: int


AGENTS = (
    AgentSpec("Pathfinder", "tas_search", 0.97, 0.80, 0.03, 0.05, (24.0, 38.0), (2.0, 14.0), 20),
    AgentSpec("Frame Oracle", "tas_search", 1.02, 0.84, 0.03, 0.08, (22.0, 34.0), (4.0, 20.0), 210),
    AgentSpec("Gradient Gecko", "reinforcement_learning", 1.75, 1.03, 0.0, 0.30, (14.0, 28.0), (0.5, 3.0), 0),
    AgentSpec("Neural Nomad", "imitation_learning", 1.35, 1.07, 0.05, 0.15, (9.0, 16.0), (0.3, 1.5), 120),
    AgentSpec("Lab Agent Alpha", "llm_agent", 1.60, 1.12, 0.08, 0.25, (3.0, 6.0), (0.1, 0.6), 300),
    AgentSpec("Lab Agent Beta", "llm_agent", 1.55, 1.15, 0.08, 0.28, (3.0, 6.0), (0.1, 0.6), 400),
)

HUMAN_COUNT = 36
COUNTRIES = ("US", "DE", "JP", "BR", "SE", "GB", "FR", "CA", "AU", "KR", "PL", "NL")
SYLLABLES = ("ka", "zu", "mi", "ro", "ta", "ne", "vo", "li", "sa", "dex", "pi", "quo", "ran", "tor", "yu", "fen")
SUFFIXES = ("", "", "_tv", "88", "run", "_x", "speed", "plays")

SCHEMA = """
CREATE TABLE games (
    game_id INTEGER PRIMARY KEY,
    title VARCHAR NOT NULL UNIQUE,
    platform VARCHAR NOT NULL,
    release_year INTEGER NOT NULL,
    frame_rate DOUBLE NOT NULL
);
CREATE TABLE categories (
    category_id INTEGER PRIMARY KEY,
    game_id INTEGER NOT NULL REFERENCES games (game_id),
    name VARCHAR NOT NULL
);
CREATE TABLE levels (
    level_id INTEGER PRIMARY KEY,
    game_id INTEGER NOT NULL REFERENCES games (game_id),
    position INTEGER NOT NULL,
    name VARCHAR NOT NULL
);
CREATE TABLE runners (
    runner_id INTEGER PRIMARY KEY,
    handle VARCHAR NOT NULL UNIQUE,
    kind VARCHAR NOT NULL,
    method VARCHAR NOT NULL,
    country VARCHAR,
    joined_on DATE NOT NULL
);
CREATE TABLE runs (
    run_id INTEGER PRIMARY KEY,
    runner_id INTEGER NOT NULL REFERENCES runners (runner_id),
    category_id INTEGER NOT NULL REFERENCES categories (category_id),
    played_at TIMESTAMP NOT NULL,
    status VARCHAR NOT NULL,
    time_seconds DOUBLE,
    frames INTEGER,
    inputs_per_second DOUBLE NOT NULL,
    compute_hours DOUBLE
);
CREATE TABLE splits (
    run_id INTEGER NOT NULL REFERENCES runs (run_id),
    level_id INTEGER NOT NULL REFERENCES levels (level_id),
    level_seconds DOUBLE NOT NULL,
    cumulative_seconds DOUBLE NOT NULL,
    PRIMARY KEY (run_id, level_id)
);
"""

COMMENTS = {
    "games": (
        "Fictional retro games that are speedrun.",
        {
            "title": "Game title.",
            "platform": "Console the game runs on.",
            "release_year": "Year the game was released.",
            "frame_rate": "Frames per second of the console; frames / frame_rate = seconds.",
        },
    ),
    "categories": (
        "Speedrun categories: the rule set a run follows, per game (e.g. Any%, 100%).",
        {"name": "Category name. Times are only comparable within one category."},
    ),
    "levels": (
        "Levels of a game in play order.",
        {"position": "1-based order in which the level is played.", "name": "Level name."},
    ),
    "runners": (
        "Who plays: human speedrunners and AI agents.",
        {
            "handle": "Public runner name.",
            "kind": "'human' or 'ai'.",
            "method": "'rta' (human real-time attack) or the AI approach: 'tas_search', 'reinforcement_learning', "
            "'imitation_learning', 'llm_agent'.",
            "country": "ISO country code of a human runner; NULL for AI agents.",
            "joined_on": "Date of the runner's first run.",
        },
    ),
    "runs": (
        "One attempt at a category. Only completed runs have a time.",
        {
            "played_at": "When the attempt started.",
            "status": "'completed', 'reset' (abandoned by the runner) or 'dnf' (did not finish: stuck or crashed).",
            "time_seconds": "Final time in seconds; NULL unless status = 'completed'. Lower is better.",
            "frames": "Final time in frames; NULL unless status = 'completed'.",
            "inputs_per_second": "Average controller inputs per second during the attempt.",
            "compute_hours": "GPU/CPU hours an AI agent spent to produce the attempt; NULL for humans.",
        },
    ),
    "splits": (
        "Time per level reached in a run. Reset and DNF runs only have the levels they reached.",
        {
            "level_seconds": "Seconds spent in this level.",
            "cumulative_seconds": "Seconds from run start to the end of this level.",
        },
    ),
}


def generate(path: Path, seed: int = 7) -> None:
    """Write the database to `path`, replacing an existing file."""
    rng = random.Random(seed)
    games, categories, levels = _static_tables()
    runners, paces = _runners(rng)
    runs, splits = _runs(rng, categories, levels, runners, paces)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.unlink(missing_ok=True)
    with duckdb.connect(str(path)) as con:
        con.execute(SCHEMA)
        for name, frame in (
            ("games", games),
            ("categories", categories),
            ("levels", levels),
            ("runners", runners),
            ("runs", runs),
            ("splits", splits),
        ):
            con.register("frame", frame)
            con.execute(f"INSERT INTO {name} SELECT * FROM frame")
            con.unregister("frame")
        for table, (description, columns) in COMMENTS.items():
            # COMMENT ON takes no parameters; the texts are the constants above.
            con.execute(f"COMMENT ON TABLE {table} IS {_literal(description)}")
            for column, text in columns.items():
                con.execute(f"COMMENT ON COLUMN {table}.{column} IS {_literal(text)}")


def _literal(text: str) -> str:
    return "'" + text.replace("'", "''") + "'"


def _static_tables() -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    games: list[tuple[object, ...]] = []
    categories: list[tuple[object, ...]] = []
    levels: list[tuple[object, ...]] = []
    for game_id, game in enumerate(GAMES, start=1):
        games.append((game_id, game.title, game.platform, game.release_year, game.frame_rate))
        for name in game.categories:
            categories.append((len(categories) + 1, game_id, name))
        for position, name in enumerate(game.levels, start=1):
            levels.append((len(levels) + 1, game_id, position, name))
    return (
        pd.DataFrame(games, columns=["game_id", "title", "platform", "release_year", "frame_rate"]),
        pd.DataFrame(categories, columns=["category_id", "game_id", "name"]),
        pd.DataFrame(levels, columns=["level_id", "game_id", "position", "name"]),
    )


@dataclass(frozen=True)
class Pace:
    first: float
    final: float
    reset_rate: float
    dnf_rate: float
    inputs_per_second: tuple[float, float]
    compute_hours: tuple[float, float] | None
    first_day: int
    # Index into GAMES for the games this runner plays.
    games: tuple[int, ...]


def _runners(rng: random.Random) -> tuple[pd.DataFrame, list[Pace]]:
    rows: list[tuple[object, ...]] = []
    paces: list[Pace] = []
    handles: set[str] = set()
    for _ in range(HUMAN_COUNT):
        handle = _handle(rng, handles)
        first = 1.0 + abs(rng.gauss(0.22, 0.14))
        first_day = rng.randrange(0, DAYS - 120)
        games = tuple(rng.sample(range(len(GAMES)), rng.choice((1, 1, 2, 3))))
        paces.append(Pace(first, max(1.0, first * rng.uniform(0.9, 0.98)), 0.55, 0.03, (4.0, 9.0), None, first_day, games))
        rows.append((len(rows) + 1, handle, "human", "rta", rng.choice(COUNTRIES), (START + timedelta(days=first_day)).date()))
    for agent in AGENTS:
        games = tuple(range(len(GAMES)))
        paces.append(
            Pace(
                agent.first_pace,
                agent.final_pace,
                agent.reset_rate,
                agent.dnf_rate,
                agent.inputs_per_second,
                agent.compute_hours,
                agent.first_day,
                games,
            )
        )
        rows.append((len(rows) + 1, agent.handle, "ai", agent.method, None, (START + timedelta(days=agent.first_day)).date()))
    return pd.DataFrame(rows, columns=["runner_id", "handle", "kind", "method", "country", "joined_on"]), paces


def _handle(rng: random.Random, taken: set[str]) -> str:
    while True:
        name = "".join(rng.choice(SYLLABLES) for _ in range(rng.choice((2, 3)))).capitalize() + rng.choice(SUFFIXES)
        if name not in taken:
            taken.add(name)
            return name


def _runs(
    rng: random.Random,
    categories: pd.DataFrame,
    levels: pd.DataFrame,
    runners: pd.DataFrame,
    paces: list[Pace],
) -> tuple[pd.DataFrame, pd.DataFrame]:
    # Level weights (share of a run) and how much a frame-perfect search can skip per level, fixed per level.
    weights = {level_id: rng.uniform(0.6, 1.4) for level_id in levels["level_id"]}
    exploits = {level_id: rng.choice((1.0, 1.0, 0.9, 0.75, 0.55)) for level_id in levels["level_id"]}
    runs: list[tuple[object, ...]] = []
    splits: list[tuple[object, ...]] = []
    for runner, pace in zip(runners.itertuples(), paces, strict=True):
        is_ai = runner.kind == "ai"
        for game_index in pace.games:
            game = GAMES[game_index]
            game_id = game_index + 1
            game_levels = levels.loc[levels["game_id"] == game_id, "level_id"].tolist()
            total_weight = sum(weights[level_id] for level_id in game_levels)
            for category in categories.loc[categories["game_id"] == game_id].itertuples():
                attempts = rng.randrange(60, 140) if is_ai else rng.randrange(8, 60)
                reference = game.categories[str(category.name)]
                for day in sorted(rng.randrange(pace.first_day, DAYS) for _ in range(attempts)):
                    progress = (day - pace.first_day) / max(1, DAYS - pace.first_day)
                    run_pace = pace.first + (pace.final - pace.first) * progress
                    status = _status(rng, pace, progress)
                    reached = len(game_levels) if status == "completed" else rng.randrange(1, len(game_levels))
                    run_id = len(runs) + 1
                    elapsed = 0.0
                    for level_id in game_levels[:reached]:
                        exploit = exploits[level_id] if runner.method == "tas_search" else 1.0
                        level_seconds = reference * weights[level_id] / total_weight * run_pace * exploit * rng.gauss(1.0, 0.025)
                        elapsed += level_seconds
                        splits.append((run_id, level_id, round(level_seconds, 3), round(elapsed, 3)))
                    played_at = START + timedelta(days=day, minutes=rng.randrange(0, 24 * 60))
                    completed = status == "completed"
                    compute = None if pace.compute_hours is None else round(rng.uniform(*pace.compute_hours), 2)
                    runs.append(
                        (
                            run_id,
                            runner.runner_id,
                            category.category_id,
                            played_at,
                            status,
                            round(elapsed, 3) if completed else None,
                            round(elapsed * game.frame_rate) if completed else None,
                            round(rng.uniform(*pace.inputs_per_second), 2),
                            compute,
                        )
                    )
    run_columns = [
        "run_id",
        "runner_id",
        "category_id",
        "played_at",
        "status",
        "time_seconds",
        "frames",
        "inputs_per_second",
        "compute_hours",
    ]
    run_frame = pd.DataFrame(runs, columns=run_columns).astype({"frames": "Int64"})
    return run_frame, pd.DataFrame(splits, columns=["run_id", "level_id", "level_seconds", "cumulative_seconds"])


def _status(rng: random.Random, pace: Pace, progress: float) -> str:
    # AI agents get stuck less as they train; humans reset most attempts that start badly.
    dnf_rate = pace.dnf_rate * (1.0 - 0.6 * progress)
    roll = rng.random()
    if roll < pace.reset_rate:
        return "reset"
    if roll < pace.reset_rate + dnf_rate:
        return "dnf"
    return "completed"


def main() -> None:
    target = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("data/speedruns.duckdb")
    generate(target)
    print(f"Wrote {target}")


if __name__ == "__main__":
    main()
