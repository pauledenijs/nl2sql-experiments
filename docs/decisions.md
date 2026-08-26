# Decision log

## 2026-08-26 - Environment and data strategy

**Database runs in Docker rather than installed natively.**

Because anyone cloning the repo gets the exact environment with one command, and because pgvector normally requires compiling.

**pgvector/pgvector:pg17 image from day one, not vanilla postgres:17.**

Because Phase 2 needs vector search for schema retrieval, and swapping the image later means a fresh volume plus a data migration. Baking the extension in now is free.

**Host port 5433, not 5432.**

Because 5432 is already spoken for by any native Postgres on the dev box. One less "port already in use" fight.

**Init scripts numbered `01_schema`/`02_grants`.**

Because they run in filename order, and you can't grant SELECT on tables that don't exist yet.

**Credentials via .env, not in the compose file.**

Because 'docker-compose.yml' is public and '.env' is gitignored, so secrets stay out of the repo while '.env.example' still documents the required variables.

**Synthetic participant data, real stimuli.**

Because the eval harness needs a ground-truth answer for every one of the 50 questions, and with generated effects the truth is known by construction. Against a real corpus you'd be comparing the agent's query to your own, and a shared bug silently agrees with itself.
