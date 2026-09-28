import sqlite3
import re
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

    CREATE TABLE IF NOT EXISTS result_links (
        result_link_id INTEGER PRIMARY KEY AUTOINCREMENT,
        result_id INTEGER NOT NULL,
        result_snapshot_id INTEGER NOT NULL,
        result_race_observation_id INTEGER NOT NULL,
        result_runner_observation_id INTEGER NOT NULL,
        pre_race_snapshot_id INTEGER NOT NULL,
        pre_race_race_id INTEGER NOT NULL,
        pre_race_runner_id INTEGER NOT NULL,
        beaten_distance TEXT,
        result_status TEXT NOT NULL,
        dead_heat_group TEXT,
        FOREIGN KEY (result_id) REFERENCES results(result_id),
        FOREIGN KEY (result_snapshot_id) REFERENCES result_snapshots(result_snapshot_id),
        FOREIGN KEY (result_snapshot_id, result_race_observation_id)
            REFERENCES result_race_observations(result_snapshot_id, result_race_observation_id),
        FOREIGN KEY (result_snapshot_id, result_runner_observation_id)
            REFERENCES result_runner_observations(result_snapshot_id, result_runner_observation_id),
        FOREIGN KEY (pre_race_snapshot_id, pre_race_race_id)
            REFERENCES races(snapshot_id, race_id),
        FOREIGN KEY (pre_race_race_id, pre_race_runner_id)
            REFERENCES runners(race_id, runner_id),
        UNIQUE(result_runner_observation_id)
    );
CREATE INDEX IF NOT EXISTS idx_result_links_snapshot
    ON result_links(result_snapshot_id);

CREATE INDEX IF NOT EXISTS idx_result_links_pre_race
    ON result_links(pre_race_snapshot_id, pre_race_race_id, pre_race_runner_id);

CREATE TABLE IF NOT EXISTS result_snapshot_details (
    result_snapshot_id INTEGER PRIMARY KEY,
    source_path TEXT,
    source_format TEXT NOT NULL,
    source_mime_type TEXT,
    source_encoding TEXT,
    source_byte_count INTEGER NOT NULL,
    source_bytes BLOB,
    FOREIGN KEY (result_snapshot_id) REFERENCES result_snapshots(result_snapshot_id)
);

CREATE TABLE IF NOT EXISTS result_snapshots (
    result_snapshot_id INTEGER PRIMARY KEY AUTOINCREMENT,
    source TEXT NOT NULL,
    captured_at TEXT NOT NULL,
    source_url TEXT,
    notes TEXT,
    content_sha256 TEXT NOT NULL UNIQUE
);

CREATE TABLE IF NOT EXISTS result_race_observations (
    result_race_observation_id INTEGER PRIMARY KEY AUTOINCREMENT,
    result_snapshot_id INTEGER NOT NULL,
    snapshot_date TEXT NOT NULL,
    course TEXT NOT NULL,
    race_time TEXT NOT NULL,
    race_number INTEGER,
    race_name TEXT,
    race_status TEXT NOT NULL,
    match_status TEXT NOT NULL CHECK (match_status IN ('unmatched', 'ambiguous', 'matched', 'manually_confirmed')),
    matched_pre_race_snapshot_id INTEGER,
    matched_pre_race_race_id INTEGER,
    evidence_json TEXT,
    raw_payload_json TEXT,
    FOREIGN KEY (result_snapshot_id) REFERENCES result_snapshots(result_snapshot_id),
    FOREIGN KEY (matched_pre_race_snapshot_id, matched_pre_race_race_id)
        REFERENCES races(snapshot_id, race_id),
    UNIQUE(result_snapshot_id, snapshot_date, course, race_time, race_number)
);

CREATE TABLE IF NOT EXISTS result_runner_observations (
    result_runner_observation_id INTEGER PRIMARY KEY AUTOINCREMENT,
    result_snapshot_id INTEGER NOT NULL,
    result_race_observation_id INTEGER NOT NULL,
    horse_number INTEGER,
    horse_name TEXT NOT NULL,
    finishing_position INTEGER,
    beaten_distance TEXT,
    result_status TEXT NOT NULL,
    starting_price TEXT,
    bsp REAL,
    dead_heat_group TEXT,
    match_status TEXT NOT NULL CHECK (match_status IN ('unmatched', 'ambiguous', 'matched', 'manually_confirmed')),
    matched_pre_race_snapshot_id INTEGER,
    matched_pre_race_race_id INTEGER,
    matched_pre_race_runner_id INTEGER,
    evidence_json TEXT,
    raw_payload_json TEXT,
    FOREIGN KEY (result_snapshot_id) REFERENCES result_snapshots(result_snapshot_id),
    FOREIGN KEY (result_snapshot_id, result_race_observation_id)
        REFERENCES result_race_observations(result_snapshot_id, result_race_observation_id),
    FOREIGN KEY (matched_pre_race_snapshot_id, matched_pre_race_race_id)
        REFERENCES races(snapshot_id, race_id),
    FOREIGN KEY (matched_pre_race_race_id, matched_pre_race_runner_id)
        REFERENCES runners(race_id, runner_id),
    UNIQUE(result_race_observation_id, horse_number, horse_name)
);

CREATE TABLE IF NOT EXISTS result_match_confirmations (
    confirmation_id INTEGER PRIMARY KEY AUTOINCREMENT,
    result_snapshot_id INTEGER NOT NULL,
    result_race_observation_id INTEGER NOT NULL,
    result_runner_observation_id INTEGER NOT NULL UNIQUE,
    pre_race_snapshot_id INTEGER NOT NULL,
    pre_race_race_id INTEGER NOT NULL,
    pre_race_runner_id INTEGER NOT NULL,
    confirmed_by TEXT NOT NULL,
    reason TEXT NOT NULL,
    confirmed_at TEXT NOT NULL,
    FOREIGN KEY (result_snapshot_id, result_race_observation_id)
        REFERENCES result_race_observations(result_snapshot_id, result_race_observation_id),
    FOREIGN KEY (result_snapshot_id, result_runner_observation_id)
        REFERENCES result_runner_observations(result_snapshot_id, result_runner_observation_id),
    FOREIGN KEY (pre_race_snapshot_id, pre_race_race_id)
        REFERENCES races(snapshot_id, race_id),
    FOREIGN KEY (pre_race_race_id, pre_race_runner_id)
        REFERENCES runners(race_id, runner_id)
);

CREATE UNIQUE INDEX IF NOT EXISTS uq_result_race_observations_snapshot_id
    ON result_race_observations(result_snapshot_id, result_race_observation_id);

CREATE UNIQUE INDEX IF NOT EXISTS uq_result_runner_observations_snapshot_id
    ON result_runner_observations(result_snapshot_id, result_runner_observation_id);

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

CREATE INDEX IF NOT EXISTS idx_result_race_observations_snapshot
    ON result_race_observations(result_snapshot_id);

CREATE INDEX IF NOT EXISTS idx_result_runner_observations_race
    ON result_runner_observations(result_race_observation_id);

CREATE TABLE IF NOT EXISTS racecard_race_details (
    race_id INTEGER PRIMARY KEY,
    race_type TEXT,
    race_type_raw TEXT,
    prize_money_value INTEGER,
    prize_money_currency TEXT,
    prize_money_raw TEXT,
    age_restrictions TEXT,
    age_restrictions_raw TEXT,
    handicap_status TEXT,
    handicap_status_raw TEXT,
    each_way_terms_raw TEXT,
    each_way_places INTEGER,
    each_way_fraction TEXT,
    place_terms_raw TEXT,
    place_terms_json TEXT,
    source_race_id TEXT,
    source_race_url TEXT,
    source_heading_raw TEXT,
    raw_payload_json TEXT,
    FOREIGN KEY (race_id) REFERENCES races(race_id)
);

CREATE TABLE IF NOT EXISTS racecard_runner_details (
    runner_id INTEGER PRIMARY KEY,
    age INTEGER,
    sex TEXT,
    owner TEXT,
    official_rating INTEGER,
    forecast_odds_decimal REAL,
    current_odds_decimal REAL,
    headgear TEXT,
    form_normalized TEXT,
    course_indicator INTEGER CHECK (course_indicator IN (0, 1) OR course_indicator IS NULL),
    distance_indicator INTEGER CHECK (distance_indicator IN (0, 1) OR distance_indicator IS NULL),
    course_distance_indicator INTEGER CHECK (course_distance_indicator IN (0, 1) OR course_distance_indicator IS NULL),
    non_runner_reason TEXT,
    horse_number_raw TEXT,
    horse_name_raw TEXT,
    draw_raw TEXT,
    age_raw TEXT,
    sex_raw TEXT,
    weight_raw TEXT,
    jockey_raw TEXT,
    apprentice_claim_raw TEXT,
    trainer_raw TEXT,
    owner_raw TEXT,
    official_rating_raw TEXT,
    forecast_odds_raw TEXT,
    current_odds_raw TEXT,
    headgear_raw TEXT,
    form_raw TEXT,
    course_indicator_raw TEXT,
    distance_indicator_raw TEXT,
    course_distance_indicator_raw TEXT,
    non_runner_status_raw TEXT,
    raw_payload_json TEXT,
    FOREIGN KEY (runner_id) REFERENCES runners(runner_id)
);

CREATE TABLE IF NOT EXISTS racecard_race_matches (
    match_id INTEGER PRIMARY KEY AUTOINCREMENT,
    racecard_snapshot_id INTEGER NOT NULL,
    racecard_race_id INTEGER NOT NULL,
    ratings_snapshot_id INTEGER NOT NULL,
    ratings_race_id INTEGER NOT NULL,
    match_status TEXT NOT NULL CHECK (match_status IN ('matched', 'ambiguous', 'unmatched', 'manually_confirmed')),
    match_method TEXT NOT NULL,
    confidence REAL NOT NULL CHECK (confidence >= 0.0 AND confidence <= 1.0),
    evidence_json TEXT,
    created_at TEXT NOT NULL,
    FOREIGN KEY (racecard_snapshot_id, racecard_race_id)
        REFERENCES races(snapshot_id, race_id),
    FOREIGN KEY (ratings_snapshot_id, ratings_race_id)
        REFERENCES races(snapshot_id, race_id),
    UNIQUE (racecard_snapshot_id, racecard_race_id, ratings_snapshot_id, ratings_race_id)
);

CREATE TABLE IF NOT EXISTS racecard_runner_matches (
    match_id INTEGER PRIMARY KEY AUTOINCREMENT,
    race_match_id INTEGER NOT NULL,
    racecard_snapshot_id INTEGER NOT NULL,
    racecard_race_id INTEGER NOT NULL,
    racecard_runner_id INTEGER NOT NULL,
    ratings_snapshot_id INTEGER NOT NULL,
    ratings_race_id INTEGER NOT NULL,
    ratings_runner_id INTEGER NOT NULL,
    match_status TEXT NOT NULL CHECK (match_status IN ('matched', 'ambiguous', 'unmatched', 'manually_confirmed')),
    match_method TEXT NOT NULL,
    confidence REAL NOT NULL CHECK (confidence >= 0.0 AND confidence <= 1.0),
    evidence_json TEXT,
    created_at TEXT NOT NULL,
    FOREIGN KEY (race_match_id) REFERENCES racecard_race_matches(match_id),
    FOREIGN KEY (racecard_snapshot_id, racecard_race_id)
        REFERENCES races(snapshot_id, race_id),
    FOREIGN KEY (racecard_race_id, racecard_runner_id)
        REFERENCES runners(race_id, runner_id),
    FOREIGN KEY (ratings_snapshot_id, ratings_race_id)
        REFERENCES races(snapshot_id, race_id),
    FOREIGN KEY (ratings_race_id, ratings_runner_id)
        REFERENCES runners(race_id, runner_id),
    UNIQUE (racecard_snapshot_id, racecard_race_id, racecard_runner_id,
            ratings_snapshot_id, ratings_race_id, ratings_runner_id)
);

CREATE INDEX IF NOT EXISTS idx_racecard_race_matches_racecard
    ON racecard_race_matches(racecard_snapshot_id, racecard_race_id);

CREATE INDEX IF NOT EXISTS idx_racecard_race_matches_ratings
    ON racecard_race_matches(ratings_snapshot_id, ratings_race_id);

CREATE INDEX IF NOT EXISTS idx_racecard_runner_matches_racecard
    ON racecard_runner_matches(racecard_snapshot_id, racecard_race_id, racecard_runner_id);

CREATE INDEX IF NOT EXISTS idx_racecard_runner_matches_ratings
    ON racecard_runner_matches(ratings_snapshot_id, ratings_race_id, ratings_runner_id);
"""


_RATINGS_HUB_COLUMNS = (
    "ratings_id, snapshot_id, race_id, runner_id, official_rating, "
    "last_winning_rating, speed, form, scope, conditions, trainer_attribute, "
    "jockey_attribute, attitude, form_plus, form_speed_average, form_minus_speed, "
    "form_plus_minus_form, form_plus_minus_speed"
)
_LEGACY_RESULTS_COLUMNS = (
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
        """INSERT INTO results__integrity_migration
           (result_id, race_id, runner_id, finishing_position, result_text,
            starting_price, bsp, winner, placed)
           SELECT result_id, race_id, runner_id, finishing_position, result_text,
                  starting_price, bsp, winner, placed
           FROM results"""
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


def _migrate_result_lineage(connection: sqlite3.Connection) -> None:
    detail_columns = {
        row[1] for row in connection.execute("PRAGMA table_info(result_snapshot_details)")
    }
    if "source_bytes" not in detail_columns:
        connection.execute(
            "ALTER TABLE result_snapshot_details ADD COLUMN source_bytes BLOB"
        )

    previous_sequence = _sequence_value(connection, "result_links")
    connection.execute("DROP TABLE IF EXISTS result_links__lineage_migration")
    connection.execute(
        """CREATE TABLE result_links__lineage_migration (
            result_link_id INTEGER PRIMARY KEY AUTOINCREMENT,
            result_id INTEGER NOT NULL,
            result_snapshot_id INTEGER NOT NULL,
            result_race_observation_id INTEGER NOT NULL,
            result_runner_observation_id INTEGER NOT NULL,
            pre_race_snapshot_id INTEGER NOT NULL,
            pre_race_race_id INTEGER NOT NULL,
            pre_race_runner_id INTEGER NOT NULL,
            beaten_distance TEXT,
            result_status TEXT NOT NULL,
            dead_heat_group TEXT,
            FOREIGN KEY (result_id) REFERENCES results(result_id),
            FOREIGN KEY (result_snapshot_id) REFERENCES result_snapshots(result_snapshot_id),
            FOREIGN KEY (result_snapshot_id, result_race_observation_id)
                REFERENCES result_race_observations(result_snapshot_id, result_race_observation_id),
            FOREIGN KEY (result_snapshot_id, result_runner_observation_id)
                REFERENCES result_runner_observations(result_snapshot_id, result_runner_observation_id),
            FOREIGN KEY (pre_race_snapshot_id, pre_race_race_id)
                REFERENCES races(snapshot_id, race_id),
            FOREIGN KEY (pre_race_race_id, pre_race_runner_id)
                REFERENCES runners(race_id, runner_id),
            UNIQUE(result_runner_observation_id)
        )"""
    )
    connection.execute(
        """INSERT INTO result_links__lineage_migration
           (result_link_id, result_id, result_snapshot_id, result_race_observation_id,
            result_runner_observation_id, pre_race_snapshot_id, pre_race_race_id,
            pre_race_runner_id, beaten_distance, result_status, dead_heat_group)
           SELECT result_link_id, result_id, result_snapshot_id, result_race_observation_id,
                  result_runner_observation_id, pre_race_snapshot_id, pre_race_race_id,
                  pre_race_runner_id, beaten_distance, result_status, dead_heat_group
           FROM result_links"""
    )
    connection.execute("DROP TABLE result_links")
    connection.execute(
        "ALTER TABLE result_links__lineage_migration RENAME TO result_links"
    )
    connection.execute(
        "CREATE INDEX idx_result_links_snapshot ON result_links(result_snapshot_id)"
    )
    connection.execute(
        "CREATE INDEX idx_result_links_pre_race "
        "ON result_links(pre_race_snapshot_id, pre_race_race_id, pre_race_runner_id)"
    )
    _restore_sequence(connection, "result_links", previous_sequence)


def _install_result_triggers(connection: sqlite3.Connection) -> None:
    for action in ("INSERT", "UPDATE"):
        trigger_name = f"validate_result_link_match_{action.lower()}"
        connection.execute(f"DROP TRIGGER IF EXISTS {trigger_name}")
        connection.execute(
            f"""CREATE TRIGGER {trigger_name}
                BEFORE {action} ON result_links
                FOR EACH ROW
                WHEN NOT EXISTS (
                    SELECT 1
                    FROM result_race_observations race_observation
                    JOIN result_runner_observations runner_observation
                      ON runner_observation.result_snapshot_id = race_observation.result_snapshot_id
                     AND runner_observation.result_race_observation_id = race_observation.result_race_observation_id
                    JOIN results canonical_result
                      ON canonical_result.result_id = NEW.result_id
                                        WHERE race_observation.result_snapshot_id = NEW.result_snapshot_id
                      AND race_observation.result_race_observation_id = NEW.result_race_observation_id
                                            AND race_observation.race_status = 'completed'
                      AND runner_observation.result_snapshot_id = NEW.result_snapshot_id
                      AND runner_observation.result_runner_observation_id = NEW.result_runner_observation_id
                                            AND (
                                                    (race_observation.match_status IN ('matched', 'manually_confirmed')
                                                     AND race_observation.matched_pre_race_snapshot_id = NEW.pre_race_snapshot_id
                                                     AND race_observation.matched_pre_race_race_id = NEW.pre_race_race_id
                                                     AND runner_observation.match_status IN ('matched', 'manually_confirmed')
                                                     AND runner_observation.matched_pre_race_snapshot_id = NEW.pre_race_snapshot_id
                                                     AND runner_observation.matched_pre_race_race_id = NEW.pre_race_race_id
                                                     AND runner_observation.matched_pre_race_runner_id = NEW.pre_race_runner_id)
                                                    OR EXISTS (
                                                            SELECT 1 FROM result_match_confirmations confirmation
                                                            WHERE confirmation.result_snapshot_id = NEW.result_snapshot_id
                                                                AND confirmation.result_race_observation_id = NEW.result_race_observation_id
                                                                AND confirmation.result_runner_observation_id = NEW.result_runner_observation_id
                                                                AND confirmation.pre_race_snapshot_id = NEW.pre_race_snapshot_id
                                                                AND confirmation.pre_race_race_id = NEW.pre_race_race_id
                                                                AND confirmation.pre_race_runner_id = NEW.pre_race_runner_id
                                                    )
                                            )
                      AND canonical_result.race_id = NEW.pre_race_race_id
                      AND canonical_result.runner_id = NEW.pre_race_runner_id
                      AND canonical_result.finishing_position IS runner_observation.finishing_position
                      AND canonical_result.result_text IS runner_observation.result_status
                      AND canonical_result.starting_price IS runner_observation.starting_price
                      AND canonical_result.bsp IS runner_observation.bsp
                      AND canonical_result.winner IS CASE WHEN runner_observation.finishing_position = 1 THEN 1 ELSE 0 END
                      AND canonical_result.placed IS CASE
                          WHEN runner_observation.finishing_position IS NOT NULL
                           AND runner_observation.finishing_position <= 3 THEN 1 ELSE 0 END
                      AND NEW.result_status IS runner_observation.result_status
                      AND NEW.beaten_distance IS runner_observation.beaten_distance
                      AND NEW.dead_heat_group IS runner_observation.dead_heat_group
                )
                BEGIN
                    SELECT RAISE(ABORT, 'canonical result link does not match explicitly matched observations');
                END"""
        )

    for table in (
        "result_snapshots",
        "result_snapshot_details",
        "result_race_observations",
        "result_runner_observations",
        "result_match_confirmations",
        "result_links",
    ):
        for action in ("UPDATE", "DELETE"):
            trigger_name = f"immutable_{table}_{action.lower()}"
            connection.execute(f"DROP TRIGGER IF EXISTS {trigger_name}")
            connection.execute(
                f"""CREATE TRIGGER {trigger_name}
                    BEFORE {action} ON {table}
                    BEGIN
                        SELECT RAISE(ABORT, '{table} rows are immutable');
                    END"""
            )

    for action in ("UPDATE", "DELETE"):
        trigger_name = f"immutable_linked_result_{action.lower()}"
        connection.execute(f"DROP TRIGGER IF EXISTS {trigger_name}")
        connection.execute(
            f"""CREATE TRIGGER {trigger_name}
                BEFORE {action} ON results
                WHEN EXISTS (SELECT 1 FROM result_links WHERE result_id = OLD.result_id)
                BEGIN
                    SELECT RAISE(ABORT, 'canonical results with lineage are immutable');
                END"""
        )


def initialise_database(database_path: str | Path = DATABASE_PATH):
    database_path = Path(database_path)
    database_path.parent.mkdir(parents=True, exist_ok=True)

    connection = sqlite3.connect(database_path)

    try:
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("BEGIN IMMEDIATE")
        statements: list[str] = []
        current: list[str] = []
        trigger_statement = False
        for line in SCHEMA.splitlines(keepends=True):
            current.append(line)
            if "CREATE TRIGGER" in "".join(current).upper():
                trigger_statement = True
            if trigger_statement:
                complete = bool(re.search(r"\nEND;\s*$", "".join(current)))
            else:
                complete = line.rstrip().endswith(";")
            if complete:
                statements.append("".join(current))
                current = []
                trigger_statement = False
        if current and "".join(current).strip():
            statements.append("".join(current))
        for statement in statements:
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
        if migration_version > 4:
            raise RuntimeError(
            f"Database migration version {migration_version} is newer than supported version 4."
            )
        if migration_version < 1:
            _migrate_relational_integrity(connection)
            connection.execute("PRAGMA user_version = 1")
            migration_version = 1

        if migration_version < 2:
            required_result_tables = {
                "result_snapshots",
                "result_links",
                "result_snapshot_details",
                "result_race_observations",
                "result_runner_observations",
            }
            existing_tables = {
                row[0]
                for row in connection.execute(
                    "SELECT name FROM sqlite_master WHERE type = 'table'"
                )
            }
            missing_tables = required_result_tables - existing_tables
            if missing_tables:
                raise sqlite3.IntegrityError(
                    f"Results schema migration is incomplete: missing {sorted(missing_tables)!r}"
                )
            connection.execute("PRAGMA user_version = 2")

        if migration_version < 3:
            _migrate_result_lineage(connection)
            connection.execute("PRAGMA user_version = 3")
            migration_version = 3

        if migration_version < 4:
            _install_result_triggers(connection)
            connection.execute("PRAGMA user_version = 4")

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
