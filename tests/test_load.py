import subprocess
import sys
import os
from pathlib import Path

import psycopg
import pytest
from psycopg import sql

from src import load

def test_loader_help_shows_dsn_option():
    result = subprocess.run(
        [sys.executable, "src/load.py", "--help"],
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stderr
    assert "--dsn" in result.stdout

def reset_loaded_tables(conn):
    tables = {
            row[0]
            for row in conn.execute(
                "SELECT tablename FROM pg_tables WHERE schemaname = 'public'"
            )
        }
    required = {"codebook", "dataset_versions", "stimuli", "stories"}
    missing = required - tables
    if missing:
        raise RuntimeError(f"Missing test tables: {', '.join(sorted(missing))}")
        
    # Codebook is static reference data. Do not clear with loader tables.
    mutable_tables = sorted(tables - {"codebook"})
    print(mutable_tables)
    statement = sql.SQL("TRUNCATE TABLE {} RESTART IDENTITY RESTRICT").format(
        sql.SQL(", ").join(sql.Identifier("public", name) for name in mutable_tables)
    )
    conn.execute(statement)

def codebook_rows(conn):
    return conn.execute(
        "SELECT table_name, column_name, value, meaning "
        "FROM public.codebook ORDER BY table_name, column_name, value"
    ).fetchall()

@pytest.fixture
def clean_db():
    dsn = os.environ["TEST_DATABASE_URL"]

    with psycopg.connect(dsn) as conn:
        database = conn.execute("SELECT current_database()").fetchone()[0]
        if database != "nl2sql_test":
            raise RuntimeError(f"Refusing to clear database {database!r}")

        # Provisional until the test database has codebook rows to preserve.
        codebook_before = codebook_rows(conn)
        reset_loaded_tables(conn)
    
    yield dsn

    with psycopg.connect(dsn) as conn:
        codebook_after = codebook_rows(conn)
        reset_loaded_tables(conn)

    assert codebook_after == codebook_before, "Loader changed static codebook rows"

def test_valid_stub_loads_expected_rows(clean_db):
    load.main(
        {
            "stories": Path("data/source/stories.tsv"),
            "stimuli": Path("tests/fixtures/stimuli_stub.tsv"),
        },
        {"stories": 10, "stimuli": 50},
        "pytest-stub",
        0,
        "fixture-stub",
        clean_db,
    )

    with psycopg.connect(clean_db) as conn:
        assert conn.execute("SELECT count(*) FROM stories").fetchone()[0] == 10
        assert conn.execute("SELECT count(*) FROM stimuli").fetchone()[0] == 50
        assert conn.execute("SELECT count(*) FROM dataset_versions").fetchone()[0] == 1