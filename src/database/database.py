import sqlite3
from pathlib import Path


DATABASE_PATH = Path("data/database/goliath.db")


SCHEMA = """
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS snapshots (
    snapshot_id INTEGER PRIMARY KEY AUTOINCREMENT,
    source TEXT NOT NULL,
    captured_at TEXT NOT NULL,
    source_url TEXT,
    notes TEXT,
    content_sha256 TEXT NOT NULL UNIQUE
);

CREATE TABLE IF NOT EXISTS races (
    race_id INTEGER PRIMARY KEY AUTOINCREMENT,
    snapshot_id INTEGER NOT NULL,
    race_date TEXT,
    course TEXT NOT NULL,
    race_time TEXT NOT NULL,
    race_number INTEGER,
    race_name TEXT,
    class TEXT,
    distance TEXT,
    going TEXT,
    surface TEXT,
    field_size INTEGER,
    FOREIGN KEY (snapshot_id) REFERENCES snapshots(snapshot_id),
    UNIQUE(snapshot_id, course, race_time)
);

CREATE TABLE IF NOT EXISTS runners (
    runner_id INTEGER PRIMARY KEY AUTOINCREMENT,
    race_id INTEGER NOT NULL,
    horse_name TEXT NOT NULL,
    horse_number INTEGER,
    draw INTEGER,
    weight TEXT,
    jockey TEXT,
    jockey_claim TEXT,
    trainer TEXT,
    current_odds TEXT,
    non_runner INTEGER DEFAULT 0,
    FOREIGN KEY (race_id) REFERENCES races(race_id),
    UNIQUE(race_id, horse_name)
);

CREATE TABLE IF NOT EXISTS ratings_hub (
    ratings_id INTEGER PRIMARY KEY AUTOINCREMENT,
    snapshot_id INTEGER NOT NULL,
    race_id INTEGER NOT NULL,
    runner_id INTEGER NOT NULL,

    official_rating INTEGER,
    last_winning_rating INTEGER,
    speed INTEGER,
    form INTEGER,
    scope INTEGER,
    conditions INTEGER,
    trainer_attribute INTEGER,
    jockey_attribute INTEGER,
    attitude INTEGER,
    form_plus INTEGER,

    form_speed_average REAL,
    form_minus_speed INTEGER,
    form_plus_minus_form INTEGER,
    form_plus_minus_speed INTEGER,

    FOREIGN KEY (snapshot_id) REFERENCES snapshots(snapshot_id),
    FOREIGN KEY (race_id) REFERENCES races(race_id),
    FOREIGN KEY (runner_id) REFERENCES runners(runner_id),

    UNIQUE(snapshot_id, runner_id)
);

CREATE TABLE IF NOT EXISTS results (
    result_id INTEGER PRIMARY KEY AUTOINCREMENT,
    race_id INTEGER NOT NULL,
    runner_id INTEGER NOT NULL,
    finishing_position INTEGER,
    result_text TEXT,
    starting_price TEXT,
    bsp REAL,
    winner INTEGER DEFAULT 0,
    placed INTEGER DEFAULT 0,
    FOREIGN KEY (race_id) REFERENCES races(race_id),
    FOREIGN KEY (runner_id) REFERENCES runners(runner_id),
    UNIQUE(race_id, runner_id)
);

CREATE INDEX IF NOT EXISTS idx_races_date
    ON races(race_date);

CREATE INDEX IF NOT EXISTS idx_races_course
    ON races(course);

CREATE INDEX IF NOT EXISTS idx_races_snapshot
    ON races(snapshot_id);

CREATE INDEX IF NOT EXISTS idx_runners_race
    ON runners(race_id);

CREATE INDEX IF NOT EXISTS idx_ratings_snapshot
    ON ratings_hub(snapshot_id);

CREATE INDEX IF NOT EXISTS idx_ratings_race
    ON ratings_hub(race_id);

CREATE INDEX IF NOT EXISTS idx_ratings_runner
    ON ratings_hub(runner_id);

CREATE INDEX IF NOT EXISTS idx_results_race
    ON results(race_id);

CREATE INDEX IF NOT EXISTS idx_results_runner
    ON results(runner_id);
"""


def initialise_database(database_path: str | Path = DATABASE_PATH):
    database_path = Path(database_path)
    database_path.parent.mkdir(parents=True, exist_ok=True)

    connection = sqlite3.connect(database_path)

    try:
        connection.executescript(SCHEMA)
        snapshot_columns = {
            row[1] for row in connection.execute("PRAGMA table_info(snapshots)")
        }
        if "content_sha256" not in snapshot_columns:
            connection.execute("ALTER TABLE snapshots ADD COLUMN content_sha256 TEXT")
            connection.execute(
                "CREATE UNIQUE INDEX IF NOT EXISTS idx_snapshots_content_sha256 "
                "ON snapshots(content_sha256)"
            )
        connection.commit()
    finally:
        connection.close()


if __name__ == "__main__":
    initialise_database()
    print(f"Database created: {DATABASE_PATH}")
