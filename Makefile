.PHONY: up reset load-stub psql test-db test

up:
	docker compose up -d

reset:
	docker compose down -v

load-stub:
	set -a; . ./.env; set +a; \
	python src/load.py \
		--dataset-version stub-test --generator-version fixture-stub --seed 0 \
		--file stories=data/source/stories.tsv --count stories=10 \
		--file stimuli=tests/fixtures/stimuli_stub.tsv --count stimuli=50

psql:
	@set -a; . ./.env; set +a; \
	docker compose exec db psql -U $$POSTGRES_USER -d $$POSTGRES_DB

test-db:
	@set -eu; \
	set -a; \
	. ./.env; \
	set +a; \
	: "$${POSTGRES_USER:?POSTGRES_USER is missing}"; \
	docker compose exec -T db psql -v ON_ERROR_STOP=1 -U "$$POSTGRES_USER" -d postgres -c 'DROP DATABASE IF EXISTS nl2sql_test'; \
	docker compose exec -T db psql -v ON_ERROR_STOP=1 -U "$$POSTGRES_USER" -d postgres -c 'CREATE DATABASE nl2sql_test'; \
	docker compose exec -T db psql -v ON_ERROR_STOP=1 -U "$$POSTGRES_USER" -d nl2sql_test < sql/01_schema.sql; \
	docker compose exec -T db psql -v ON_ERROR_STOP=1 -U "$$POSTGRES_USER" -d nl2sql_test -c '\dt'

test:
	@set -a; . ./.env; set +a; \
	python -m pytest -q