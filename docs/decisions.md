# Decision log

## 2026-08-26 - Environment and data strategy

**Database runs in Docker rather than installed natively.**

Because anyone cloning the repo gets a consistent environment with one command, and because pgvector normally requires compiling.

**pgvector/pgvector:pg17 image from day one, not vanilla postgres:17.**

Because Phase 2 needs vector search for schema retrieval, and swapping the image later means a fresh volume plus a data migration. Baking the extension in now is free.

**Host port 5433, not 5432.**

Because 5432 is already spoken for by any native Postgres on the dev box. One less "port already in use" fight.

**Init scripts numbered `01_schema`/`02_grants`.**

Because they run in filename order, and you can't grant SELECT on tables that don't exist yet.

**Credentials via .env, not in the compose file.**

Because `docker-compose.yml` is public and `.env` is gitignored, so secrets stay out of the repo while `.env.example` still documents the required variables.

**Synthetic participant data, real stimuli.**

Because the eval harness needs a ground-truth answer for every one of the 50 questions, and with generated effects the truth is known by construction. Against a real corpus you'd be comparing the agent's query to your own, and a shared bug silently agrees with itself.

## 2026-08-28 - Design normalized schema

**Grain.**

A table's row is a claim about what one instance represents. `responses` is one row per participant per word. Getting this wrong is expensive to discover after data collection.

**Normalization.**

Surprisal is stored once per word in `stimuli`, not repeated on every participant's row. Otherwise a correction is a correction x100, and a database that disagrees with itself doesn't warn you.

**Aggregates remain queries for this benchmark.**

No stored averages, no materialized means. Roughly half the golden set is aggregation questions; if the answer is a column, the thing tested no longer exists. The query *is* the test.

**Composite key on `responses`: `participant_id` + `stimulus_id`.**

Chosen over a surrogate `id` because nothing else references `responses`. The usual cost of composite keys (every foreign key drags both columns along) never comes due.

**Self-paced reading over picture matching.**

Word-level grain gives three levels of nesting and makes spillover a `LAG()` window function, arising from a real psycholinguistic construct rather than a forced exercise.

**Derived `condition` added to `stimuli`.**

A departure from Natural Stories. It exists so tier-3 questions can write condition contrasts directly, and so tier-4 has a column to plant the 2% mislabeled rows in.

**Sessions table dropped.**

One session per participant means the table would be exactly one row per participant. A table needs to *vary* independently of the entity it's attached to.

**Codebook is context, not constraint.**

Postgres can enforce the acceptable values of a column (CHECK (l2_status IN (0,1,9))) but that doesn't ensure a query uses them correctly. WHERE l2_status > 0 will happily run but silently count the unknowns as L2 speakers. The constraint is enforced by the engine; the meaning has to be read by whoever writes the query. Traditionally, that's the human with the codebook open, here it's the agent.

Column comments could carry these definitions, but the codebook is a table so the retrieval layer gets a consistent structure across tables: one row per column value.

This is why "how many L2 participants" is a diagnostic tier-4 item: it doesn't test SQL, it tests whether retrieval put the right context in the prompt. 

## 2026-09-01 - Write tables

**Reading times stored as INTEGER.**

Millisecond-level readings are inherently discrete whole-number values, so an integer type is the natural fit. The float tolerance present in the evaluation harness governs how computed aggregates such as `AVG(rt)` are compared at query time. It is a concern at the analysis layer, not a storage concern. Conflating the two would be a category error.

**Surprisal and frequency stored as DOUBLE PRECISION.**

Both are continuous measurements rather than discrete counts, so a floating-point type is appropriate. `NUMERIC` is designed for exact fixed-point decimal arithmetic (e.g., currency) and offers no advantage here. `REAL` would truncate precision earlier than necessary, and for no corresponding saving in space or speed.

**ON DELETE RESTRICT applied to all foreign keys.**

Research datasets are expensive to reconstruct and should never be silently reduced by an unrelated `DELETE` on a parent table. `ON DELETE CASCADE` is a common mechanism by which a routine cleanup on one table cascades into unintended mass loss across related tables. `SET NULL` was considered but is not viable on the `responses` table: `participant_id` forms half of the composite primary key, and primary key columns are not nullable.

**Condition stored as unconstrained TEXT.**

A `CHECK` constraint restricting the allowed values would be the conventional choice, but doing so would undermine the benchmark itself. Tier 4 deliberately includes approximately 2% rows with mislabeled condition values to verify whether the agent notices fragmentation. A `CHECK` constraint would reject those rows at insert time, making the tier untestable. The constraint is therefore intentionally omitted to preserve the diagnostic integrity of the benchmark.

**rt declared NOT NULL.**

The schema treats absence of a reading time as the absence of a row, not as a row containing a `NULL`. This keeps the representation of missing data unambiguous. The deliberately planted 12000 ms outlier is a genuine data value that tier 4's "longest reading time" query depends on being present and queryable. Allowing `NULL` in `rt` would introduce a second, competing representation of "no reading time" alongside sentinel values, complicating downstream analysis.

**Foreign key column types must exactly match the referenced column type.**

`responses.stimulus_id` was initially declared as `SMALLINT` while the referenced `stimuli.stimulus_id` primary key is `INTEGER`. The mismatch does not surface at small scale (under 10,000 rows) but will fail silently once identifiers exceed the 32,767 upper bound of `SMALLINT`. The constraint doesn't require identity, which is why the mismatch survives creation and fails later.