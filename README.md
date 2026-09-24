# Bellabeat / Fitbit analytics case study

A reproducible portfolio study of the supplied 18 Fitbit CSVs and 27-slide case brief. The deck's “Strava” title is retained, but the data are Fitbit exports. Recommended product: **Bellabeat App/Membership**, because activity and sleep onboarding can be tested together without assuming hardware, hydration or sales evidence.

## Run

Python 3.12 was used. Allow approximately 2 GB free disk space for raw data, SQLite and exports; bounded import chunks contain 100,000 rows. Runtime depends on disk/CPU speed. The generated SQLite database is about 790 MiB and is deliberately omitted from the delivery archive. All CSV/parquet aggregates, executed outputs and 30 chart PNGs are included.

1. Extract this package; keep the `outputs/` contents together.
2. Extract your original Data Files ZIP into a sibling `raw/` directory (nested folders are supported).
3. From `outputs/`, run:

```bash
python -m pip install -r requirements.txt
python -m ipykernel install --user --name python3
python run_all.py --raw-dir ../raw
```

For environments that disallow Jupyter kernel sockets, use:

```bash
python run_all.py --raw-dir ../raw --in-process
```

The delivered notebook was executed using the socket-free IPython path; every code cell ran and real outputs were captured. For an interactive rerun, open `Bellabeat_Fitbit_EDA.ipynb` from `outputs/` and Run All. If needed, set `FITBIT_RAW_DIR` to the extracted CSV directory. The notebook rebuilds a missing database and refreshes SQL and processed outputs. Never mix another dataset release into this folder.

Individual stages:

```bash
python load_csv_to_sqlite.py --raw-dir ../raw --db bellabeat.db
python run_sql.py
python execute_notebook.py
python export_notebook.py
```

SQLite 3.25+ supports the window syntax; the correlation query additionally requires `SQRT` (available in the verified SQLite 3.53.1 build). If an older DB Browser build lacks math functions, update its SQLite build. US source dates are converted explicitly in the loader using `%m/%d/%Y` or `%m/%d/%Y %I:%M:%S %p`; SQLite stores ISO text. Do not directly import unconverted US dates and run date functions against them.

PDF export uses WeasyPrint and may require system Pango libraries on some computers. Self-contained HTML is always exported and is the fallback if PDF dependencies are unavailable. A verified PDF is already included.

## Folder structure

| Path | Content |
|---|---|
| Bellabeat_Fitbit_EDA.ipynb | Executed notebook, 16 numbered sections, 30 charts with interpretations |
| Bellabeat_Fitbit_EDA.pdf / .html | Notebook exports with saved outputs |
| Bellabeat_Fitbit_Analysis.sql | Sectioned master SQL with purpose/question/output headers |
| load_csv_to_sqlite.py | Chunked typed import, source hashes, full audits and indexes |
| run_sql.py | Executes every SQL statement and writes result CSVs |
| analysis_utils.py | Independent pandas cleaning, features, statistics, clustering and chart functions |
| execute_notebook.py | Sequential IPython runner for socket-restricted environments |
| export_notebook.py / run_all.py | Export and end-to-end orchestration |
| requirements.txt | Versions used in this execution |
| processed/ | Clean/aggregated CSV and parquet, audit tables, data dictionary and summaries |
| sql_outputs/ | Query results, main insight CSVs and execution log |
| charts/ | 30 numbered static PNGs |
| validation_report.json | Delivery checks and database-omission note |
| bellabeat.db | Rebuilt locally; omitted from archive due to size |

No Power BI file, Streamlit application or video is included in this requested scope.

## Reconciliation

Python independently cleans the three small daily/log tables and computes user summaries. SQL uses documented views. Comparisons use a tight floating-point tolerance; there are no deliberate differences in the metrics below.

| metric                 |      python |         sql | match   |
|:-----------------------|------------:|------------:|:--------|
| activity_users         |   33.000000 |   33.000000 | True    |
| clean_activity_rows    |  846.000000 |  846.000000 | True    |
| average_steps          | 8426.832151 | 8426.832151 | True    |
| clean_sleep_rows       |  410.000000 |  410.000000 | True    |
| average_sleep_minutes  |  419.173171 |  419.173171 | True    |
| clean_weight_rows      |   67.000000 |   67.000000 | True    |
| segment: Keep momentum |   18.000000 |   18.000000 | True    |
| segment: Reconnect     |    9.000000 |    9.000000 | True    |
| segment: Build routine |    6.000000 |    6.000000 | True    |

Sleep summaries use all 410 unique valid sleep days, while activity charts use 846 proxy-valid days. Thus a same-date inner join contains fewer sleep days; previous/next joins require exact dates and have different counts. This is deliberate coverage handling, not inconsistent cleaning.

## Assumptions and corrections

- Proxy-valid activity = steps >=100 and sedentary minutes <1,440. It is not verified on-body wear. Thresholds 1, 100, 500 and 1,000 are compared; unfiltered data remain available.
- Full study window is 31 dates, April 12–May 12, 2016. Wide minute files have different bounds, April 13–May 13; minute sleep starts April 11. Wide and narrow values agree on 1,278,060 overlapping minute keys per measure, but wide has 20,640 unmatched minute keys and narrow has 47,520. Do not append them together.
- 33 activity users contradict the brief's 30. Sleep has 24, HR 14 and weight eight. All three daily subset files match dailyActivity exactly.
- Sleep duplicates: three daily rows; 543 minute rows. Weight Fat missing: 65/67. Near-zero/1,440-minute days are possible nonwear, not proof of user behaviour.
- The five step tiers are descriptive historical conventions requested in the task, not a CDC universal 10,000-step requirement. Sleep bands are illustrative; age-specific needs cannot be assessed.
- Weekly activity flag is a WHO-inspired **proxy**, not clinical compliance: fairly active +2×very active >=150, evaluated only with seven retained days; a moderate-only sensitivity flag is also provided.
- Calories are treated as exported kcal and include basal expenditure. Distance, raw intensity and raw MET scale remain unresolved. No inferred sleep-state labels, sleep-onset latency or age-based HR zones are invented.
- HR duration uses next-reading intervals only when 0<gap<=60 seconds, not sample count ×15. Overnight low-HR proxy is not clinical resting HR.
- Statistical units are users. Five exploratory association/group tests use Holm adjustment; effect sizes and user-bootstrap uncertainty are reported. Clusters are exploratory, not target-population truths.

## Executive findings

1. Activity/sleep/HR/weight coverage is 33/24/14/8 users.
2. The quality proxy retains 846/940 days; raw mean steps 7,638 versus retained 8,427.
3. 45.4% of retained days record fewer than 7,500 steps.
4. Light activity accounts for 84.7% of classified active minutes.
5. Recorded movement peaks at 18:00, averaging 660 steps per observed hour.
6. Mean sleep is 419.2 minutes; 44.1% of sleep days are below seven hours.
7. Weekend-minus-weekday user mean gap is +120 steps; 95% CI -959 to +1,143, so the direction is uncertain.
8. Weight logging is concentrated: top two users contribute 80.6% of logs; 41/67 entries are manual.

## Marketing experiments

Prioritize quality-aware onboarding; personal-baseline movement campaigns; randomized reminder timing; optional sleep onboarding; and optional weight logging. Each recommendation in notebook Section 13 includes evidence, action and measurement KPIs. No conversion uplift, revenue or health effect is estimated from these files.

## Limitations

A small, self-selected 2016 convenience sample; no demographics; no confirmed wear sensor; proprietary device estimates; nonrandom missingness; partial observation days; limited sleep/HR coverage and highly concentrated weight logs. No acquisition, app-event, subscription or revenue data exist. Causal, population-wide and women-specific conclusions would be unsupported.

References: [WHO physical activity](https://www.who.int/news-room/fact-sheets/detail/physical-activity), [CDC sleep](https://www.cdc.gov/sleep/about/index.html). Dataset provenance is as stated in the supplied brief, including DOI 10.5281/zenodo.53894; no independent license/provenance certification is claimed.

## Verification

58 master-SQL statements executed successfully. All nine reconciliation metrics passed. The notebook has 45 executed code cells and 30 embedded images, with no error outputs or warning clutter. CSV/parquet pair consistency, chart presence and PDF rendering were checked. See validation_report.json and sql_outputs/execution_log.csv.
