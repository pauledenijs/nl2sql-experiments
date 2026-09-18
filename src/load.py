import os, csv, argparse
from pathlib import Path
from graphlib import TopologicalSorter
import psycopg
from psycopg.types.json import Jsonb
from psycopg import sql

FK_SQL = """
SELECT conrelid::regclass::text AS child,
    confrelid::regclass::text AS parent
FROM pg_constraint
WHERE contype = 'f' 
AND connamespace = 'public'::regnamespace
"""

SCHEMA_TABLES_SQL = """
SELECT tablename
FROM pg_catalog.pg_tables
WHERE schemaname = 'public'
ORDER BY tablename"""

# dataset_versions must not be in COLUMNS because it is not loaded from tsv. 
DATASET_VERSION_INSERT = """
INSERT INTO dataset_versions (
    dataset_version,
    generated_at,
    generator_version,
    seed,
    generation_parameters,
    expected_aggregates,
    observed_aggregates,
    row_counts,
    validation_status
)
VALUES (%s, now(), %s, %s, %s, %s, NULL, %s, 'valid')
"""

COLUMNS = {
    "stories": (
        "story_id",
        "title"
    ),
    "stimuli": (
        "stimulus_id",
        "story_id",
        "sentence_num",
        "word_position",
        "word",
        "zipf_frequency",
        "surprisal_nats"
    ),
}

# These are the only fixture tables required today
REQUIRED_TABLES = frozenset({"stories", "stimuli"})

EMPTINESS_CHECK_EXCLUSIONS = frozenset({"codebook"})

def inspect_tsv(path):
    with path.open(encoding="utf-8", newline="") as source:
        rows = csv.reader(source, delimiter="\t")
        try:
            header = tuple(next(rows))
        except StopIteration:
            raise ValueError(f"{path}: file is empty") from None
        return header, sum(1 for _ in rows)

def load_order(cur, tables):
    graph = {t:set() for t in tables}
    cur.execute(FK_SQL)
    for child, parent in cur.fetchall():
        if child in graph and parent in graph:
            graph[child].add(parent)
    return list(TopologicalSorter(graph).static_order())

def assert_database_empty(cur):
    cur.execute(SCHEMA_TABLES_SQL)
    checked_tables = [
        table
        for table, in cur.fetchall()
        if table not in EMPTINESS_CHECK_EXCLUSIONS
    ]
    if not checked_tables:
        return

    query = sql.SQL(" UNION ALL ").join(
        sql.SQL("SELECT {} WHERE EXISTS (SELECT 1 FROM {})").format(
            sql.Literal(table), sql.Identifier("public", table)
        )
        for table in checked_tables
    )
    cur.execute(query)
    nonempty = sorted(table for table, in cur.fetchall())
    if nonempty:
        raise RuntimeError(
            "database is not empty; refusing to load. "
            f"Non-empty tables: {', '.join(nonempty)}. "
            "Reset the dataset tables explicitly before loading another version."
        )

def copy_table(cur, table, path, columns):
    command = sql.SQL(
        r"COPY {} ({}) FROM STDIN "
        r"WITH (FORMAT csv, DELIMITER E'\t', HEADER MATCH, NULL '\N')"
    ).format(
        sql.Identifier(table),
        sql.SQL(", ").join(map(sql.Identifier, columns)),
    )
    with path.open("rb") as source:
        with cur.copy(command) as copy:
            while chunk := source.read(65_536):
                copy.write(chunk)
    return cur.rowcount

def main(files, counts, dataset_version, seed, generator_version, dsn):
    if set(files) != REQUIRED_TABLES:
        raise ValueError(
            f"required tables are {sorted(REQUIRED_TABLES)}, "
            f"received {sorted(files)}"
        )

    if files.keys() != counts.keys():
        raise ValueError("--file and --count must name the same tables")

    for table, path in files.items():
        header, found = inspect_tsv(path)
        expected_header = COLUMNS[table]
        if header != expected_header:
            raise ValueError(
                f"{table}: expected header {expected_header}, found {header}"
            )
        if found != counts[table]:
            raise ValueError(
                f"{table}: expected {counts[table]} TSV rows, found {found}"
            )
    with psycopg.connect(dsn) as conn:
        with conn.cursor() as cur:
            assert_database_empty(cur)
            order = load_order(cur, files.keys())

            for table in order:
                loaded = copy_table(cur, table, files[table], COLUMNS[table])
                if loaded != counts[table]:
                    raise RuntimeError(
                        f"{table}: expected {counts[table]}, loaded {loaded}"
                    )
            cur.execute(
                DATASET_VERSION_INSERT,
                (
                    dataset_version,
                    generator_version,
                    seed,
                    Jsonb({"files": {t: str(p) for t, p in files.items()}}),
                    Jsonb({}),
                    Jsonb(counts),
                )
            )
    return order

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--dsn", default=os.getenv("DATABASE_URL"))
    parser.add_argument("--dataset-version", required=True)
    parser.add_argument("--generator-version", default="fixture-stub")
    parser.add_argument("--seed", required=True, type=int)
    parser.add_argument("--file", action="append", required=True)
    parser.add_argument(
        "--count", 
        action="append", 
        required=True,
        help="expected TABLE=ROWS claim (the generator will supply this later)",
    )
    args = parser.parse_args()

    if not args.dsn:
        parser.error("set DATABASE_URL or pass --dsn")

    files = {
        table: Path(path)
        for table, path in (item.split("=", 1) for item in args.file)
    }
    counts = {
        table: int(count)
        for table, count in (item.split("=", 1) for item in args.count)
    }

    loaded_order = main(
        files,
        counts,
        args.dataset_version,
        args.seed,
        args.generator_version,
        args.dsn,
    )
    print(f"loaded {args.dataset_version}: {', '.join(loaded_order)}")