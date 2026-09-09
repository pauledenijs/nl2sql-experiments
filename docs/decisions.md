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

Millisecond-level readings are inherently discrete whole-number values, so an integer type is the natural fit. The float tolerance present in the evaluation harness governs how computed aggregates such as `AVG(rt)` are compared at query time. It is a concern at the analysis layer, not a storage con                  cern. Conflating the two would be a category error.

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

## 2026-09-05 - Postgres-only build; read-only role and grants

**Postgres from the start.**

Postgres 17 + pgvector in Docker, no DuckDB stage, no later engine port.

Starting with DuckDB would have built a temporary path that couldn't demonstrate the role boundary, per-role session settings, or the final grant model, then required a dialect and infrastructure port before production. Starting with Postgres keeps the database engine and the SQL surface aligned across phases.

Docker Postgres and managed Postgres are not the same environment. Provisioning, authentication, extensions, networking, backups, and operational permissions will differ. But they are the same engine, which removes an otherwise unnecessary application and schema migration.

DuckDB's strongest benefit here was faster local schema iteration. The schema had already been designed before implementation, so that benefit wasn't large enough to justify the temporary path.

**The read-only role and its controls.**

Role creation and grants live in `sql/02_grants.sh`, not a .sql file.

A shell file is not required to keep the password out of source control. A psql-driven .sql file could read `NL2SQL_RO_PASSWORD` with `\getenv`, branch with `\if`, and fail on errors. The official image already runs .sql files with `ON_ERROR_STOP`.

The shell file is an organizational choice. It is the clearer place to validate that the environment variable exists, invoke psql, and keep credential-dependent bootstrap work separate from schema DDL. The extension tells a reader that this is environmental setup rather than another part of the data model.

The password is safe only if the shell passes it to psql as a variable and SQL uses psql's literal quoting, `:'variable'`. Expanding it directly into a heredoc would mishandle quotes and turn the environment value into SQL text. The password stays out of git only while `.env` remains ignored and uncommitted. Compose environment variables are acceptable for local development, not the Phase 5 secret-management design.

The mixed extensions in the init directory are deliberate. One line in the `README` will record that fact so nobody has to infer whether it was intentional.

**All five capability-bearing negative attributes stated explicitly: NOSUPERUSER, NOCREATEROLE, NOREPLICATION, NOBYPASSRLS, NOCREATEDB.**

Because the grants file is a document as much as it is code. A reviewer can read the intended role boundary directly instead of reconstructing it from PostgreSQL defaults. 

All five are currently defaults, so spelling them out does not add a new enforcement layer. It records the contract and prevents role creation from depending silently on those defaults. `LOGIN` is also explicit because this is a connection identity, not only a group role.

**Separate controls for table writes and object creation.**

The SELECT-only grant is the durable object-level control on the application tables. `nl2sql_ro` has `SELECT`, not `INSERT`, `UPDATE`, `DELETE`, `TRUNCATE`, `REFERENCES`, `TRIGGER`, or `MAINTAIN`. Turning off the read-only transaction default does not grant any of those privileges. 

That grant is irrelevant to `CREATE TABLE`. Two separate controls currently stand between `nl2sql_ro` and a regular table in public:

1. `default_transaction_read_only = on` rejects `CREATE TABLE` because PostgreSQL disallows `CREATE` in a read-only transaction. 

2. If a role turns that setting off, it still has `USAGE` but not `CREATE` on schema `public`. PostgreSQL removed `CREATE` on public from `PUBLIC` for new databases in version 15. Upgraded or restored databases can retain the older permission, so the test suite must assert the actual schema privilege rather than rely only on the server version. 

Tested with the default active: `CREATE TABLE` as `nl2sql_ro` returns `ERROR: cannot execute CREATE TABLE in a read-only transaction`.

The second layer still needs its own test:

Set `default_transaction_read_only = off` as `nl2sql_ro`. Attempt to create a regular table in `public`. Confirm that it fails for lack of schema `CREATE`.

Temporary tables are a separate privilege surface. PostgreSQL grants database `TEMPORARY` to `PUBLIC` by default. Once the role turns off its read-only default, it may still be able to create and write temporary tables. That is acceptable only if the boundary means "cannot change application data or persistent schema." If the boundary means "cannot perform any write," database `TEMPORARY` also has to be addressed.

Executable functions and role memberships are separate surfaces as well. SELECT-only table grants are the hard control on direct access to those tables, not a complete proof that every callable database operation is read-only.

**statement_timeout and default_transaction_read_only set on the role, not only in the client.**

Because the default belongs to the identity, not to one caller. Every session that logs in directly as `nl2sql_ro` receives both settings: agent, psql, a notebook, or a future second service.

A client-side setting would require every caller to remember it. A role default gives new direct-login sessions the intended starting state automatically.

The boundary is narrower than "every session using the role." PostgreSQL applies role settings at login. A connection authenticated as another identity and followed by `SET ROLE nl2sql_ro` does not receive them.

Both settings are `USERSET`. The session can turn them off, and the role can change its own future session defaults. `statement_timeout` is therefore a resource guardrail, and `default_transaction_read_only` is a write-safety guardrail. Neither is an authorization boundary. The grants underneath them are what protect application objects after deliberate override.

**Both GRANT SELECT ON ALL TABLES and ALTER DEFAULT PRIVILEGES.**

Because default privileges aren't retroactive. They govern objects created after the command runs. The seven existing tables therefore need the snapshot grant, while default privileges cover tables created later. 

Neither command alone covers both existing and future objects.

Default privileges attach to the role that creates the object, in the current database. They are not inherited from roles that the creator happens to belong to. The command should therefore name the intended owner with `FOR ROLE` rather than leave that relationship implicit.

A table created by any other owner role will not automatically become visible to `nl2sql_ro`. That is a silent omission rather than a creation error. Phase 5 needs this in its runbook if a second owner role appears.

**Open item (not yet resolved)**

Role creation currently lives in the local environment layer, not the portable database-provisioning layer.

`02_grants.sh` depends on the Docker entrypoint. Managed Postgres has no Compose file and no `/docker-entrypoint-initdb.d`. Docker init scripts also run only against an empty data directory, so changing this file does not update an existing local cluster.

The role is reproducible anywhere the Docker project is initialized from an empty volume with the required environment, but there is no artifact that provisions or reconciles it on a managed instance.

Phase 5 owes a provider-compatible bootstrap script, infrastructure definition, or documented runbook step. Due before Phase 5 exits development.

**TCP authentication verified; password enforced.**

Closed 2026-09-05.

The container's `pg_hba.conf` has trust for local Unix-socket connections and an entrypoint-appended `scram-sha-256` catch-all for TCP connections.

A host connection to the published container port does not originate from the container's `127.0.0.1/32`. It therefore does not match the loopback trust rule. It falls through to the TCP catch-all, where the `nl2sql_ro` password is enforced rather than bypassed.

Verified on 5 September 2026 over TCP as `nl2sql_ro`: an incorrect password was rejected with `FATAL: password authentication failed`; the configured password authenticated successfully.

Rejected: leaving the password untested until Phase 2. That would have carried a known authentication gap forward for no benefit and made the first psycopg connection responsible for discovering bootstrap errors. 

Accepted: publish PostgreSQL as `127.0.0.1:5433:5432` and verify the final connection path now. The loopback-only binding gives host-side psycopg and evaluation code access on port 5433 without exposing PostgreSQL on every host interface. Loopback binding and `scram` are independent controls: the binding limits who can reach PostgreSQL while `scram` makes reachability insufficient without a password.

## 2026-09-07 - Phase 1 schema closure

**rt removed, superseding the 1 September decision.**

Because rt is exactly `offset_ms` - `onset_ms` when both timestamps use the same session clock. Storing all three creates two sources of truth and permits rt to disagree with the timestamps. Queries calculate it when needed. The 1 September entry remains in the log as the record of the earlier decision.

**Singleton dataset versioning, not per-row versioning.**

Because only one generated dataset needs to be loaded at a time. Per-row versioning would add `dataset_version_id` to fact-table keys and require a version predicate in all golden-set questions; one omitted predicate could silently mix versions. The dataset_versions manifest keeps the seed, generator version, parameters, timestamp, aggregates, and validation history without putting a version foreign key on every fact row.

**03_codebook.sql is the source of truth; docs/codebook.md is generated from it.**

Because the SQL codebook is what the agent queries and what can be validated against the live schema. Maintaining an independently editable Markdown copy would allow meanings to drift. If the files disagree, 03_codebook.sql wins and docs/codebook.md is regenerated.

**stimuli.condition stays stored even though its canonical value is derivable from surprisal.**

Because `condition` is a semantic classification produced by generator policy, not a lossless arithmetic identity. It freezes the surprisal constrast used by tier-3 questions and preserves the deliberately noncanonical labels emitted for 2 percent of rows. Recomputing `condition` in every query would duplicate the threshold rule, allow the golden questions to define the contrast differently, and erase the label-normalization problem those rows are intended to test.

This is the asymmetry with rt: rt has one exact formula and should never disagres with its inputs. `condition` represents a versioned analytical decision and its stored surface label is deliberately allowed to differ from the canonical label. `surprisal` remains the numeric source used to validate the classification; `condition` remains the generated categorical value used for contrasts and normalization tests.

## 2026-09-09 - Stimulus ingestion and loading

### Decided

**Natural Stories text will be committed to the repository and not fetched at build time.**

Because downloading it during the build would create an external build dependency and could undermine reproducibility if the upstream corpus changed.

**The repository will use separate licenses for code and data.**

Because separate licensing keeps the applicable terms for corpus-derived data distinct from independently written code; a single repo-wide license would either over-restrict the code or misrepresent the data.

**Natural Stories `item` maps to story and `zone` to word.**

Because preserving the corpus coordinates provides a stable source mapping.

**`word_position` will be numbered within each sentence.**

Because its meaning must remain stable and unambiguous across stories and sentences.

**`word` will preserve corpus punctuation with normalization performed only for lexical lookup.**

Because the stored stimulus preserves the punctuated form required as input to surprisal computation.

**Word length will be derived rather than stored.**

Because it is a deterministic property of the stored word and should not become a second value that can drift out of agreement.

**`condition` will be stored on `responses`, not `stimuli`, superseding the 2026-09-01 decision.**

Because condition is generated contamination rather than a Natural Stories annotation and therefore belongs with the generated observations.

**Zipf frequency will come from SUBTLEX and remain nullable.**

Because proper nouns and rare forms may have no SUBTLEX match, and absence is not equivalent to zero frequency. 

**Surprisal will be stored in nats.**

Because the unit must be explicit and consistent across generation, storage, and analysis.

**Tables will load in a topological ordering of the foreign-key graph.**

Because every referenced parent row must exist before its dependent rows are loaded.

**The generator, not PostgreSQL, will assign keys shared across generated TSVs.**

Because files such as `stimuli.tsv` and `responses.tsv` must agree on `stimulus_id` before loading, and `stimuli.stimulus_id` is `NOT NULL` with no default. The same inputs and generation seed must produce the same keys.

**Generated tab-separated files will use `\N` for NULL and load with `HEADER MATCH`.**

Because the writer and PostgreSQL must share an explicit missing-value marker, while header validation prevents column-name and ordering drift.

**The dataset manifest will begin with `validation_status = 'pending'` and change to `valid` only after all validation and loading operations succeed.** 

Because an incomplete or partially loaded dataset version must never be exposed as valid.

**The repository's `./data/source` directory will be mounted read-only inside the database container at `/data`.**

Because the loader needs a stable in-container path but must not modify committed source data.

### Open

**Surprisal provenance remains open and must be decided before the stub is replaced with the full Natural Stories file.**

Because the storage unit is fixed as nats, but the source model, model version, tokenizer, and subword-to-word aggregation method have not yet been selected.

**The `responses` schema must gain a `condition` column before the generator writes `responses.tsv`.**

Because `condition` must be materialized, but the current table has no column to store it.

**The unit at which noncanonical condition labels are planted remains open and must be decided before response generation.**

Because planting per response allows two participants to receive different labels for the same stimulus, while planting once per stimulus and copying the label to every response produces consistent stimulus-level dirt.

**Whether punctuation counts toward analytical word length remains open and must be decided before word-length questions are finalized.**

Because the current default is `length(word)`, which counts the characters in the stored punctuated form, while punctuation-stripped character counting has not been implemented.

### Verified today

**`\N` and `HEADER MATCH` load successfully.**

Observed output: `COPY 50`.

**An empty string in a numeric field is rejected rather than silently converted to zero.**

Observed output: `ERROR: invalid input syntax for type double precision`.

**A nullable Zipf frequency survives the TSV-to-PostgreSQL round trip as SQL NULL.**

Observed output: `SELECT count(*) FROM stimuli WHERE zipf_frequency IS NULL;` returned `1`.

**A quoted stimulus survives CSV parsing correctly.**

Observed output: the TSV field `"""If"` loaded as `"If`, and PostgreSQL returned a character length of `3`.