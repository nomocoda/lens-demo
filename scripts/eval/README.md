# Atlas SaaS synthetic dataset generator

Stage 1 Relevance Engine eval. Generates a deterministic synthetic dataset for
a fictional B2B SaaS company ("Atlas SaaS", ~250 employees, mid-market focus)
that seeds the 15 locked VP Marketing Story Card patterns from
`lens-demo/index.html` (`insightData.marketing.cards`, indexes 0-14).

Reference "today" is 2026-04-24; the dataset covers the trailing 12 months.

## Setup

```sh
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
```

## Run

```sh
# JSON (Stage 1 direct feed): one file per entity in ./output/
.venv/bin/python generate_dataset.py --seed 42 --output ./output

# CSV (Stage 2 HubSpot import): one CSV per entity
.venv/bin/python generate_dataset.py --seed 42 --format csv --output ./output_csv

# Re-validate an existing output directory without regenerating
.venv/bin/python generate_dataset.py --validate --output ./output
```

Every run ends with a 15-check validation report that computes each card's
implied signal pattern from the generated data and asserts the gap falls inside
the target band (e.g. P01: current-week marketing-sourced DTC vs. trailing-11w
DTC, gap 10-18 days). Exit code is 0 only when 15/15 pass.

## Output shape

16 entities. JSON mode writes one `.json` file per entity under `--output`:

- `companies.json` (800 rows)
- `contacts.json` (3000)
- `deals.json` (~600)
- `campaigns.json` (~33)
- `campaign_performance.json`
- `budget.json`, `actual_spend.json`
- `engagement_events.json` (~10K)
- `branded_search.json` (weekly)
- `web_analytics.json` (daily, per channel)
- `mentions.json` (daily), `competitors.json`
- `analyst_mentions.json`
- `customer_reference_optins.json`
- `product_launches.json`, `sdr_capacity.json`

## Seeder invariants

Each pattern seeder owns a slice of the data; other seeders and the filler pool
avoid stepping on it. The important invariants:

- `paid_social` / `paid_search` lead sources are reserved for p04.
- `events` lead source is reserved for p06.
- Closed enterprise deals are reserved for p03 (so its win-rate math is clean).
- Filler closed deals use only non-marketing sources so they don't drift p01
  (marketing-sourced DTC) or p06 (events DTC) means.

Card-to-seeder mapping with line references lives in the module docstring.

## Reproducibility

All randomness routes through a single seeded `random.Random` plus a seeded
`Faker` instance. The same `--seed` produces byte-identical output on reruns.
Validation passes across multiple seeds (tested: 1, 7, 42, 99, 2026).

## Out of scope

- Running the dataset through the Relevance Engine (next handoff).
- HubSpot CSV import validation (Stage 2).
- Any lens-demo frontend changes.
