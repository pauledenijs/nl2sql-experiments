.PHONY: up down load-stub

up:
	docker compose up -d

down:
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