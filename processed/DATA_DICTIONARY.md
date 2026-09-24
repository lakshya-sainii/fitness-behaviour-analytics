# Processed data contract

Each analytical CSV has an identically named parquet companion. Id is an identifier (64-bit integer), not a numeric feature. Dates are timezone-naive because the source has no timezone metadata. Missing values remain NULL/NaN and must not be replaced by zero without a business rule.

| Dataset | Grain / keys | Purpose |
|---|---|---|
| clean_daily_activity | Id + date, unique | 846 proxy-valid days; canonical steps, device minutes and total calories |
| flagged_daily_activity | Id + date, unique | All 940 activity days with valid_day flag for sensitivity and exclusion audit |
| clean_sleep | Id + date, unique | 410 unique sleep days; sleep efficiency and in-bed gap |
| clean_weight | Id + Date/LogId | 67 logs, not necessarily unique user-day; aggregate before day joins |
| user_summary | Id, unique | Coverage, mean retained-day behaviour, rule segment and exploratory persona |
| hourly_activity | Id + ActivityHour, unique | Observed hours on retained activity dates; step/calorie/intensity joins |
| hr_hourly | Id + ActivityHour, unique | HR readings aggregated without expanding gaps |
| hr_bands | Id + bpm_band | Interval-weighted descriptive bpm bands; observed_seconds excludes gaps >60 sec |
| hr_intensity_join | Id + ActivityHour, unique | Exact overlapping HR/intensity/raw-MET user-hours |
| met_hourly | Id + ActivityHour, unique | Raw MET field mean and recorded minute count; scale unverified |
| resting_proxy | Id, unique | Overnight 10th percentile of hourly mean HR; not clinical resting HR |
| minute_sleep_logs | Id + logId, unique | 459 deduplicated episodes; raw state-code counts |
| sleep_activity_pairs | Id + date, unique | SleepDay aligned with exact previous, same and next activity date |
| weekly_activity | Id + study_week, unique | Four 7-day windows; guideline-inspired flags NULL unless 7 valid days |
| source_inventory | table_name, unique | File sizes, SHA256, grain, date bounds, row/user/duplicate counts |
| column_audit | table_name + column_name | All source fields, SQLite type, missing and negative counts |
| cleaning_log | transformation | Before/after rows and columns; justification |
| quality_scorecard | check | Count, status and interpretation; no arbitrary quality percentage |
| threshold_sensitivity | minimum_steps | Alternative proxy thresholds with retained days and mean steps |
| redundancy_checks | comparison | Daily and wide/narrow parity on overlapping keys |
| cluster_selection | k | Inertia and silhouette for k=2 through 6 |
| cluster_profiles | cluster | Original-scale persona centroids and user counts |
| statistical_tests | test + comparison | User-level effects, p-values and Holm correction |
| sleep_lag_statistics | alignment | Pair counts, user counts, median within-user rho and bootstrap CI |
| reconciliation | metric | Independent Python vs SQL values and pass flag |

## Engineered fields

- valid_day: TotalSteps >=100 and SedentaryMinutes <1440; a quality proxy, not confirmed wear.
- weekday: Monday through Sunday; weekend: Saturday/Sunday =1.
- study_day: April 12 =1; study_week: seven-day windows from April 12.
- hour_bucket: Night 00–05, Morning 06–11, Afternoon 12–17, Evening 18–23.
- steps_category: <5000 sedentary, 5000–7499 low active, 7500–9999 somewhat active, 10000–12499 active, >=12500 highly active; descriptive tiers.
- active_minutes: light + fairly + very active minutes.
- active_share: active / (active + sedentary device-classified minutes); not actual wear fraction.
- moderate_equivalent: fairly active + 2 × very active minutes.
- calories_per_step: total daily kcal / steps; not movement-only energy efficiency.
- sleep_efficiency: TotalMinutesAsleep / TotalTimeInBed; ratio 0–1.
- in_bed_gap: TotalTimeInBed minus TotalMinutesAsleep; not sleep-onset latency.
- engagement_score: 100 × retained activity days /31; observation proxy, not app interaction or motivation.
- who_proxy: weekly moderate_equivalent >=150 only when seven proxy-valid days exist; unknown otherwise.
- moderate_only_flag: fairly active minutes >=150 using the same complete-week condition.
- rule_segment: <21 valid days Reconnect; otherwise <7500 mean steps Build routine; else Keep momentum.
- cluster/persona: exploratory standardized KMeans on mean_steps, mean_active_share and engagement_score.

Raw column definitions and cautions appear in notebook Section 1; column_audit is the exhaustive field list. Summary, findings and recommendations are reporting artifacts, not new observations. Do not join raw minute or weight logs directly onto daily tables without first aggregating to the intended grain.
