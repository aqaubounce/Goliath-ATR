import sqlite3
from pathlib import Path


DATABASE_PATH = Path("data/database/goliath.db")


SCHEMA = """
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

CREATE UNIQUE INDEX IF NOT EXISTS uq_races_snapshot_race_id
    ON races(snapshot_id, race_id);

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

CREATE UNIQUE INDEX IF NOT EXISTS uq_runners_race_runner_id
    ON runners(race_id, runner_id);

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
    FOREIGN KEY (snapshot_id, race_id)
        REFERENCES races(snapshot_id, race_id),
    FOREIGN KEY (race_id, runner_id)
        REFERENCES runners(race_id, runner_id),

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
    FOREIGN KEY (race_id, runner_id)
        REFERENCES runners(race_id, runner_id),
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

CREATE INDEX IF NOT EXISTS idx_ratings_snapshot_race
    ON ratings_hub(snapshot_id, race_id);

CREATE INDEX IF NOT EXISTS idx_ratings_race_runner
    ON ratings_hub(race_id, runner_id);

CREATE INDEX IF NOT EXISTS idx_results_race
    ON results(race_id);

CREATE INDEX IF NOT EXISTS idx_results_runner
    ON results(runner_id);
"""


_RATINGS_HUB_COLUMNS = (
    "ratings_id, snapshot_id, race_id, runner_id, official_rating, "
    "last_winning_rating, speed, form, scope, conditions, trainer_attribute, "
    "jockey_attribute, attitude, form_plus, form_speed_average, form_minus_speed, "
    "form_plus_minus_form, form_plus_minus_speed"
)
_RESULTS_COLUMNS = (
    "result_id, race_id, runner_id, finishing_position, result_text, "
    "starting_price, bsp, winner, placed"
)


def _has_composite_foreign_key(
    connection: sqlite3.Connection,
    table: str,
    parent_table: str,
    source_columns: tuple[str, ...],
    target_columns: tuple[str, ...],
) -> bool:
    foreign_keys: dict[int, list[tuple[int, str, str, str]]] = {}
    for row in connection.execute(f"PRAGMA foreign_key_list({table})"):
        foreign_keys.setdefault(row[0], []).append((row[1], row[2], row[3], row[4]))
    return any(
        entries[0][1] == parent_table
        and tuple(entry[2] for entry in sorted(entries)) == source_columns
        and tuple(entry[3] for entry in sorted(entries)) == target_columns
        for entries in foreign_keys.values()
    )


def _sequence_value(connection: sqlite3.Connection, table: str) -> int | None:
    row = connection.execute(
        "SELECT seq FROM sqlite_sequence WHERE name = ?", (table,)
    ).fetchone()
    return row[0] if row is not None else None


def _restore_sequence(
    connection: sqlite3.Connection, table: str, previous_value: int | None
) -> None:
    if previous_value is None:
        return
    row = connection.execute(
        "SELECT seq FROM sqlite_sequence WHERE name = ?", (table,)
    ).fetchone()
    if row is None:
        connection.execute(
            "INSERT INTO sqlite_sequence(name, seq) VALUES (?, ?)",
            (table, previous_value),
        )
    elif row[0] < previous_value:
        connection.execute(
            "UPDATE sqlite_sequence SET seq = ? WHERE name = ?",
            (previous_value, table),
        )


def _rebuild_ratings_hub(connection: sqlite3.Connection) -> None:
    previous_sequence = _sequence_value(connection, "ratings_hub")
    connection.execute(
        """CREATE TABLE ratings_hub__integrity_migration (
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
            FOREIGN KEY (snapshot_id, race_id)
                REFERENCES races(snapshot_id, race_id),
            FOREIGN KEY (race_id, runner_id)
                REFERENCES runners(race_id, runner_id),
            UNIQUE(snapshot_id, runner_id)
        )"""
    )
    connection.execute(
        f"INSERT INTO ratings_hub__integrity_migration ({_RATINGS_HUB_COLUMNS}) "
        f"SELECT {_RATINGS_HUB_COLUMNS} FROM ratings_hub"
    )
    connection.execute("DROP TABLE ratings_hub")
    connection.execute(
        "ALTER TABLE ratings_hub__integrity_migration RENAME TO ratings_hub"
    )
    connection.execute("CREATE INDEX idx_ratings_snapshot ON ratings_hub(snapshot_id)")
    connection.execute("CREATE INDEX idx_ratings_race ON ratings_hub(race_id)")
    connection.execute("CREATE INDEX idx_ratings_runner ON ratings_hub(runner_id)")
    connection.execute(
        "CREATE INDEX idx_ratings_snapshot_race ON ratings_hub(snapshot_id, race_id)"
    )
    connection.execute(
        "CREATE INDEX idx_ratings_race_runner ON ratings_hub(race_id, runner_id)"
    )
    _restore_sequence(connection, "ratings_hub", previous_sequence)


def _rebuild_results(connection: sqlite3.Connection) -> None:
    previous_sequence = _sequence_value(connection, "results")
    connection.execute(
        """CREATE TABLE results__integrity_migration (
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
            FOREIGN KEY (race_id, runner_id)
                REFERENCES runners(race_id, runner_id),
            UNIQUE(race_id, runner_id)
        )"""
    )
    connection.execute(
        f"INSERT INTO results__integrity_migration ({_RESULTS_COLUMNS}) "
        f"SELECT {_RESULTS_COLUMNS} FROM results"
    )
    connection.execute("DROP TABLE results")
    connection.execute(
        "ALTER TABLE results__integrity_migration RENAME TO results"
    )
    connection.execute("CREATE INDEX idx_results_race ON results(race_id)")
    connection.execute("CREATE INDEX idx_results_runner ON results(runner_id)")
    _restore_sequence(connection, "results", previous_sequence)


def _migrate_relational_integrity(connection: sqlite3.Connection) -> None:
    connection.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_races_snapshot_race_id "
        "ON races(snapshot_id, race_id)"
    )
    connection.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_runners_race_runner_id "
        "ON runners(race_id, runner_id)"
    )

    ratings_hub_is_constrained = all(
        (
            _has_composite_foreign_key(
                connection,
                "ratings_hub",
                "races",
                ("snapshot_id", "race_id"),
                ("snapshot_id", "race_id"),
            ),
            _has_composite_foreign_key(
                connection,
                "ratings_hub",
                "runners",
                ("race_id", "runner_id"),
                ("race_id", "runner_id"),
            ),
        )
    )
    if not ratings_hub_is_constrained:
        _rebuild_ratings_hub(connection)

    if not _has_composite_foreign_key(
        connection,
        "results",
        "runners",
        ("race_id", "runner_id"),
        ("race_id", "runner_id"),
    ):
        _rebuild_results(connection)

    violations = connection.execute("PRAGMA foreign_key_check").fetchall()
    if violations:
        raise sqlite3.IntegrityError(
            f"Composite foreign-key migration produced violations: {violations!r}"
        )


def initialise_database(database_path: str | Path = DATABASE_PATH):
    database_path = Path(database_path)
    database_path.parent.mkdir(parents=True, exist_ok=True)

    connection = sqlite3.connect(database_path)

    try:
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("BEGIN IMMEDIATE")
        for statement in SCHEMA.split(";"):
            if statement.strip():
                connection.execute(statement)

        snapshot_columns = {
            row[1] for row in connection.execute("PRAGMA table_info(snapshots)")
        }
        if "content_sha256" not in snapshot_columns:
            connection.execute("ALTER TABLE snapshots ADD COLUMN content_sha256 TEXT")
            connection.execute(
                "CREATE UNIQUE INDEX IF NOT EXISTS idx_snapshots_content_sha256 "
                "ON snapshots(content_sha256)"
            )

        migration_version = connection.execute("PRAGMA user_version").fetchone()[0]
        if migration_version > 1:
            raise RuntimeError(
                f"Database migration version {migration_version} is newer than supported version 1."
            )
        if migration_version < 1:
            _migrate_relational_integrity(connection)
            connection.execute("PRAGMA user_version = 1")

        violations = connection.execute("PRAGMA foreign_key_check").fetchall()
        if violations:
            raise sqlite3.IntegrityError(
                f"Database contains foreign-key violations: {violations!r}"
            )
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


if __name__ == "__main__":
    initialise_database()
    print(f"Database created: {DATABASE_PATH}")
