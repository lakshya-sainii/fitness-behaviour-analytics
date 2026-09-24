"""Independent pandas cleaning, bounded aggregates, validation and chart utilities."""

from __future__ import annotations
import json
import sqlite3
from pathlib import Path
import numpy as np
import pandas as pd
from scipy import stats
from sklearn.cluster import KMeans
from sklearn.metrics import silhouette_score, adjusted_rand_score
from sklearn.preprocessing import StandardScaler

SEED = 42
PALETTE = ["#0072B2", "#E69F00", "#009E73", "#CC79A7", "#D55E00", "#56B4E9"]
TIERS = ["Sedentary", "Low active", "Somewhat active", "Active", "Highly active"]
DAY_ORDER = [
    "Monday",
    "Tuesday",
    "Wednesday",
    "Thursday",
    "Friday",
    "Saturday",
    "Sunday",
]


def save_frame(frame: pd.DataFrame, name: str, base: Path) -> None:
    """Save matching portable CSV and typed, compressed parquet artifacts."""
    frame.to_csv(base / "processed" / f"{name}.csv", index=False)
    frame.to_parquet(base / "processed" / f"{name}.parquet", index=False)


def prepare_data(base: Path, verbose: bool = True) -> dict:
    """Read small tables and bounded SQL aggregates; clean daily tables independently."""
    con = sqlite3.connect(base / "bellabeat.db")
    read = lambda sql: pd.read_sql_query(sql, con)
    raw = read("SELECT * FROM dailyActivity")
    sleep_raw = read("SELECT * FROM sleepDay")
    weight_raw = read("SELECT * FROM weightLogInfo")
    inventory = read("SELECT * FROM source_inventory")
    columns = read("SELECT * FROM column_audit")
    log = []

    def record(issue, action, before, after, why):
        log.append(
            dict(
                issue=issue,
                action=action,
                rows_before=before[0],
                rows_after=after[0],
                columns_before=before[1],
                columns_after=after[1],
                justification=why,
            )
        )
        if verbose:
            print(
                f"{action}: {before[0]:,} rows x {before[1]} -> {after[0]:,} rows x {after[1]}"
            )

    d = raw.drop_duplicates().copy()
    record(
        "Exact activity duplicates",
        "Deduplicate activity",
        raw.shape,
        d.shape,
        "Retain one identical record",
    )
    d["date"] = pd.to_datetime(d.ActivityDate, format="%Y-%m-%d")
    d["valid_day"] = (d.TotalSteps >= 100) & (d.SedentaryMinutes < 1440)
    flagged = d.copy()
    d = d.loc[d.valid_day].copy()
    record(
        "Probable nonwear / negligible motion",
        "Apply wear-quality proxy",
        flagged.shape,
        d.shape,
        "Steps >=100 and sedentary <1440; excludes true low movement too; sensitivity reported",
    )
    before = d.shape
    d["weekday"] = d.date.dt.day_name()
    d["weekend"] = (d.date.dt.dayofweek >= 5).astype(int)
    d["study_day"] = (d.date - pd.Timestamp("2016-04-12")).dt.days + 1
    d["study_week"] = (d.study_day - 1) // 7 + 1
    d["steps_category"] = pd.cut(
        d.TotalSteps, [0, 5000, 7500, 10000, 12500, np.inf], labels=TIERS, right=False
    )
    d["active_minutes"] = d[
        ["VeryActiveMinutes", "FairlyActiveMinutes", "LightlyActiveMinutes"]
    ].sum(axis=1)
    d["active_share"] = d.active_minutes / (d.active_minutes + d.SedentaryMinutes)
    d["moderate_equivalent"] = d.FairlyActiveMinutes + 2 * d.VeryActiveMinutes
    d["calories_per_step"] = d.Calories / d.TotalSteps
    record(
        "Analytical features",
        "Engineer daily features",
        before,
        d.shape,
        "Active share denominator is classified minutes; calories include basal expenditure",
    )
    s = sleep_raw.drop_duplicates().copy()
    record(
        "Exact sleep duplicates",
        "Deduplicate sleep",
        sleep_raw.shape,
        s.shape,
        "Remove identical daily records",
    )
    before = s.shape
    s = s.loc[
        (s.TotalMinutesAsleep > 0)
        & (s.TotalTimeInBed >= s.TotalMinutesAsleep)
        & (s.TotalTimeInBed <= 1440)
    ].copy()
    record(
        "Impossible sleep values",
        "Validate sleep",
        before,
        s.shape,
        "Positive duration, asleep <= in-bed <=1440",
    )
    s["date"] = pd.to_datetime(s.SleepDay, format="%Y-%m-%d %H:%M:%S")
    s["sleep_efficiency"] = s.TotalMinutesAsleep / s.TotalTimeInBed
    s["in_bed_gap"] = s.TotalTimeInBed - s.TotalMinutesAsleep
    s["sleep_hours"] = s.TotalMinutesAsleep / 60
    s["sleep_band"] = pd.cut(
        s.sleep_hours,
        [0, 7, 9, np.inf],
        right=False,
        labels=["<7 h", "7 to <9 h", "9+ h"],
    )
    s["weekday"] = s.date.dt.day_name()
    w = weight_raw.drop_duplicates().copy()
    w = w.loc[(w.WeightKg > 0) & (w.BMI > 0)].copy()
    record(
        "Weight validity and missing Fat",
        "Validate weight; retain missing Fat",
        weight_raw.shape,
        w.shape,
        "No imputation; analyse logging, not weight change or health",
    )
    w["date"] = pd.to_datetime(w.Date, format="%Y-%m-%d %H:%M:%S").dt.normalize()
    assert not d.duplicated(["Id", "date"]).any()
    assert not s.duplicated(
        ["Id", "date"]
    ).any(), "Resolve conflicting daily sleep keys before merging"
    u = (
        raw.groupby("Id")
        .agg(
            days_logged=("ActivityDate", "nunique"),
            first_date=("ActivityDate", "min"),
            last_date=("ActivityDate", "max"),
        )
        .join(
            d.groupby("Id").agg(
                valid_days=("date", "size"),
                mean_steps=("TotalSteps", "mean"),
                mean_active=("active_minutes", "mean"),
                mean_sedentary=("SedentaryMinutes", "mean"),
                mean_calories=("Calories", "mean"),
                mean_active_share=("active_share", "mean"),
            )
        )
        .reset_index()
    )
    u["valid_days"] = u.valid_days.fillna(0).astype(int)
    u["engagement_score"] = 100 * u.valid_days / 31
    u["days_logged"] = u.days_logged.astype(int)
    u["rule_segment"] = np.select(
        [u.valid_days < 21, u.mean_steps < 7500],
        ["Reconnect", "Build routine"],
        default="Keep momentum",
    )
    u["sleep_logger"] = u.Id.isin(s.Id)
    u = u.merge(
        s.groupby("Id").agg(
            mean_sleep=("TotalMinutesAsleep", "mean"), sleep_days=("date", "size")
        ),
        on="Id",
        how="left",
    )
    d = d.merge(u[["Id", "days_logged"]], on="Id", validate="many_to_one")
    hour = read("SELECT * FROM hourly_activity")
    hour["date"] = pd.to_datetime(hour.activity_date, format="%Y-%m-%d")
    hour["weekday"] = hour.date.dt.day_name()
    hour["hour_bucket"] = pd.cut(
        hour.hour,
        [-1, 5, 11, 17, 23],
        labels=["Night", "Morning", "Afternoon", "Evening"],
    )
    record(
        "Hourly coverage",
        "Restrict hours to retained activity dates",
        (int(inventory.loc[inventory.table_name == "hourlySteps", "rows"].iloc[0]), 3),
        hour.shape,
        "No imputation for absent hours; averages use observed user-hours",
    )
    hr = read("SELECT * FROM hr_hourly")
    bands = read("SELECT * FROM hr_bands")
    met = read("SELECT * FROM met_hourly")
    hr_join = hr.merge(
        hour[["Id", "ActivityHour", "TotalIntensity"]],
        on=["Id", "ActivityHour"],
        validate="one_to_one",
    ).merge(met, on=["Id", "ActivityHour"], validate="one_to_one")
    night = hr.loc[hr.ActivityHour.str[11:13].astype(int).between(0, 5)]
    resting = (
        night.groupby("Id").mean_bpm.quantile(0.1).rename("night_p10_bpm").reset_index()
    )
    episodes = read("SELECT * FROM minute_sleep_logs")
    record(
        "Duplicate minute sleep rows",
        "Aggregate unique sleep minutes to episodes",
        (int(inventory.loc[inventory.table_name == "minuteSleep", "rows"].iloc[0]), 4),
        episodes.shape,
        "Exact deduplication in SQL; raw code labels not interpreted as clinical stages",
    )
    # No carry-forward: adjacent-day joins require exact calendar dates.
    pairs = s[["Id", "date", "TotalMinutesAsleep"]].copy()
    for lag, name in [(0, "same"), (-1, "previous"), (1, "next")]:
        other = d[["Id", "date", "TotalSteps"]].copy()
        other["date"] = other.date - pd.Timedelta(days=lag)
        pairs = pairs.merge(
            other.rename(columns={"TotalSteps": name + "_steps"}),
            on=["Id", "date"],
            how="left",
            validate="one_to_one",
        )
    weekly = (
        d.loc[d.study_week <= 4]
        .groupby(["Id", "study_week"])
        .agg(
            valid_days=("date", "size"),
            moderate_equivalent=("moderate_equivalent", "sum"),
            moderate_minutes=("FairlyActiveMinutes", "sum"),
        )
        .reset_index()
    )
    weekly["who_proxy"] = np.where(
        weekly.valid_days == 7, (weekly.moderate_equivalent >= 150).astype(int), np.nan
    )
    weekly["moderate_only_flag"] = np.where(
        weekly.valid_days == 7, (weekly.moderate_minutes >= 150).astype(int), np.nan
    )
    # Sensitivity quantifies the selection introduced by proxy thresholds.
    sensitivity = pd.DataFrame(
        [
            {
                "minimum_steps": t,
                "days": int(
                    ((raw.TotalSteps >= t) & (raw.SedentaryMinutes < 1440)).sum()
                ),
                "mean_steps": raw.loc[
                    (raw.TotalSteps >= t) & (raw.SedentaryMinutes < 1440), "TotalSteps"
                ].mean(),
            }
            for t in [1, 100, 500, 1000]
        ]
    )
    # Confirm daily subsets, and wide/narrow equality only on overlapping keys.
    redundancy = []
    for table, value in [
        ("dailySteps", "StepTotal"),
        ("dailyCalories", "Calories"),
        ("dailyIntensities", None),
    ]:
        b = read(f"SELECT * FROM {table}").rename(
            columns={"ActivityDay": "ActivityDate", "StepTotal": "TotalSteps"}
        )
        merged = raw.merge(
            b, on=["Id", "ActivityDate"], suffixes=("_a", "_b"), validate="one_to_one"
        )
        measures = [c for c in b if c not in ["Id", "ActivityDate"]]
        mismatches = sum(
            int((~np.isclose(merged[c + "_a"], merged[c + "_b"], atol=1e-6)).sum())
            for c in measures
        )
        redundancy.append(
            dict(
                comparison=table + " vs dailyActivity",
                overlap_rows=len(merged),
                missing_keys=len(b) - len(merged),
                mismatched_values=mismatches,
            )
        )
    for stem, measure in [
        ("Steps", "Steps"),
        ("Intensities", "Intensity"),
        ("Calories", "Calories"),
    ]:
        wide = read(f"SELECT * FROM minute{stem}Wide")
        wide = wide.set_index(["Id", "ActivityHour"])
        total_overlap = total_mismatch = 0
        for chunk in pd.read_sql_query(
            f"SELECT * FROM minute{stem}Narrow", con, chunksize=100000
        ):
            stamp = pd.to_datetime(chunk.ActivityMinute, format="%Y-%m-%d %H:%M:%S")
            keys = pd.MultiIndex.from_arrays(
                [chunk.Id, stamp.dt.strftime("%Y-%m-%d %H:00:00")]
            )
            positions = wide.index.get_indexer(keys)
            exists = positions >= 0
            expected = wide.to_numpy()[
                positions[exists], stamp.dt.minute.to_numpy()[exists]
            ]
            total_overlap += int(exists.sum())
            total_mismatch += int(
                (~np.isclose(expected, chunk.loc[exists, measure], atol=1e-5)).sum()
            )
        redundancy.append(
            dict(
                comparison="minute" + stem + " wide/narrow",
                overlap_rows=total_overlap,
                missing_keys=len(wide) * 60 - total_overlap,
                mismatched_values=total_mismatch,
            )
        )
    redundancy = pd.DataFrame(redundancy)
    # Standardize nonredundant activity and engagement features, one observation/user.
    features = ["mean_steps", "mean_active_share", "engagement_score"]
    cluster_users = u.dropna(subset=features).copy()
    X = StandardScaler().fit_transform(cluster_users[features])
    scores = []
    for k in range(2, 7):
        km = KMeans(n_clusters=k, random_state=SEED, n_init=30).fit(X)
        scores.append(
            dict(k=k, inertia=km.inertia_, silhouette=silhouette_score(X, km.labels_))
        )
    scores = pd.DataFrame(scores)
    best_k = int(scores.loc[scores.silhouette.idxmax(), "k"])
    km = KMeans(n_clusters=best_k, random_state=SEED, n_init=30).fit(X)
    cluster_users["cluster"] = km.labels_
    profile = cluster_users.groupby("cluster")[features].mean()
    ordered = profile.mean_steps.sort_values().index.tolist()
    names = {
        label: f'{["Gentle starters","Routine builders","Steady movers","Momentum seekers","Active regulars","High-step enthusiasts"][i]}'
        for i, label in enumerate(ordered)
    }
    cluster_users["persona"] = cluster_users.cluster.map(names)
    profile["persona"] = profile.index.map(names)
    profile["users"] = cluster_users.groupby("cluster").size()
    profile = profile.reset_index()
    stability = [
        adjusted_rand_score(
            km.labels_,
            KMeans(n_clusters=best_k, random_state=seed, n_init=30).fit_predict(X),
        )
        for seed in range(10)
    ]
    u = u.merge(
        cluster_users[["Id", "cluster", "persona"]],
        on="Id",
        how="left",
        validate="one_to_one",
    )
    # Independent statistical unit is user, not the hundreds of repeated daily records.
    tests = []
    for col in ["mean_steps", "mean_active", "mean_calories"]:
        v = u[col].dropna()
        t = stats.shapiro(v)
        tests.append(
            dict(
                test="Shapiro-Wilk",
                comparison=col,
                n=len(v),
                statistic=t.statistic,
                p_value=t.pvalue,
                effect_size=np.nan,
                effect_definition="W reported in statistic",
            )
        )
    for x, y in [
        ("mean_steps", "mean_calories"),
        ("mean_steps", "mean_sleep"),
        ("mean_active", "mean_sleep"),
    ]:
        v = u[[x, y]].dropna()
        t = stats.spearmanr(v[x], v[y])
        tests.append(
            dict(
                test="Spearman",
                comparison=x + " / " + y,
                n=len(v),
                statistic=t.statistic,
                p_value=t.pvalue,
                effect_size=t.statistic,
                effect_definition="Spearman rho; one mean per user",
            )
        )
    a = u.loc[u.sleep_logger, "mean_steps"].dropna()
    b = u.loc[~u.sleep_logger, "mean_steps"].dropna()
    t = stats.mannwhitneyu(a, b, alternative="two-sided")
    delta = 2 * t.statistic / (len(a) * len(b)) - 1
    tests.append(
        dict(
            test="Mann-Whitney U",
            comparison="Sleep loggers vs nonloggers: mean steps",
            n=len(a) + len(b),
            statistic=t.statistic,
            p_value=t.pvalue,
            effect_size=delta,
            effect_definition="Cliff delta; positive favors sleep loggers",
        )
    )
    wk = d.groupby(["Id", "weekend"]).TotalSteps.mean().unstack().dropna()
    dif = wk[1] - wk[0]
    t = stats.wilcoxon(dif)
    ranks = stats.rankdata(abs(dif[dif != 0]))
    sg = np.sign(dif[dif != 0])
    rbc = float((ranks * sg).sum() / ranks.sum())
    tests.append(
        dict(
            test="Wilcoxon paired",
            comparison="Weekend minus weekday user mean steps",
            n=len(dif),
            statistic=t.statistic,
            p_value=t.pvalue,
            effect_size=rbc,
            effect_definition="Matched rank-biserial; positive favors weekend",
        )
    )
    tests = pd.DataFrame(tests)
    # Holm adjustment on association/group tests; normality checks are diagnostics.
    tests["p_holm"] = np.nan
    ix = tests.index[tests.test != "Shapiro-Wilk"]
    ps = tests.loc[ix, "p_value"].to_numpy()
    order = np.argsort(ps)
    adj = np.minimum(
        1, np.maximum.accumulate(ps[order] * (len(ps) - np.arange(len(ps))))
    )
    tests.loc[ix[order], "p_holm"] = adj
    rng = np.random.default_rng(SEED)
    bootstrap = np.array(
        [
            rng.choice(dif.to_numpy(), size=len(dif), replace=True).mean()
            for _ in range(2000)
        ]
    )
    lag_rows = []
    for label in ["previous", "same", "next"]:
        vals = []
        for uid, g in pairs.groupby("Id"):
            v = g[["TotalMinutesAsleep", label + "_steps"]].dropna()
            if len(v) >= 5 and v.nunique().min() > 1:
                vals.append(stats.spearmanr(v.iloc[:, 0], v.iloc[:, 1]).statistic)
        ci = np.percentile(
            [np.median(rng.choice(vals, len(vals), replace=True)) for _ in range(2000)],
            [2.5, 97.5],
        )
        lag_rows.append(
            dict(
                alignment=label,
                users=len(vals),
                pairs=int(pairs[label + "_steps"].notna().sum()),
                median_within_user_rho=np.median(vals),
                ci_low=ci[0],
                ci_high=ci[1],
            )
        )
    lag_stats = pd.DataFrame(lag_rows)
    sql = read("SELECT * FROM user_summary")
    metrics = dict(
        activity_users=raw.Id.nunique(),
        clean_activity_rows=len(d),
        average_steps=d.TotalSteps.mean(),
        clean_sleep_rows=len(s),
        average_sleep_minutes=s.TotalMinutesAsleep.mean(),
        clean_weight_rows=len(w),
    )
    sql_metrics = pd.read_csv(base / "sql_outputs/reconciliation.csv").iloc[0]
    recon = pd.DataFrame(
        [
            dict(
                metric=k,
                python=float(v),
                sql=float(sql_metrics[k]),
                match=bool(np.isclose(v, sql_metrics[k], rtol=1e-10)),
            )
            for k, v in metrics.items()
        ]
    )
    for seg, n in u.rule_segment.value_counts().items():
        other = int((sql.rule_segment == seg).sum())
        recon.loc[len(recon)] = {
            "metric": "segment: " + seg,
            "python": n,
            "sql": other,
            "match": n == other,
        }
    assert recon["match"].all()
    assert np.allclose(
        u.sort_values("Id").mean_steps, sql.sort_values("Id").mean_steps, equal_nan=True
    )
    quality = pd.DataFrame(
        [
            ["Participants vs brief", 33, "Review", "33 activity users vs 30 stated"],
            [
                "Exact sleep duplicates",
                int(sleep_raw.duplicated().sum()),
                "Fixed",
                "413 raw rows -> 410 unique",
            ],
            [
                "Minute sleep duplicates",
                int(
                    inventory.loc[
                        inventory.table_name == "minuteSleep", "duplicate_rows"
                    ].iloc[0]
                ),
                "Fixed",
                "Deduplicated before episode aggregation",
            ],
            [
                "Zero-step days",
                int((raw.TotalSteps == 0).sum()),
                "Flagged",
                "May be nonwear or true inactivity",
            ],
            [
                "Near-zero days (<100)",
                int((raw.TotalSteps < 100).sum()),
                "Excluded",
                "Proxy threshold; sensitivity table retained",
            ],
            [
                "Sedentary =1440",
                int((raw.SedentaryMinutes == 1440).sum()),
                "Excluded",
                "24 hours; does not establish actual nonwear",
            ],
            [
                "Classified minutes >1440",
                int(
                    (
                        raw[
                            [
                                "VeryActiveMinutes",
                                "FairlyActiveMinutes",
                                "LightlyActiveMinutes",
                                "SedentaryMinutes",
                            ]
                        ].sum(axis=1)
                        > 1440
                    ).sum()
                ),
                "Review",
                "Impossible full-day duration if present",
            ],
            [
                "Missing Fat",
                int(w.Fat.isna().sum()),
                "Retained",
                "Do not impute sparse body-fat field",
            ],
            [
                "Multiple sleep records",
                int((s.TotalSleepRecords > 1).sum()),
                "Retained",
                "Possible split sleep/naps; no automatic deletion",
            ],
            [
                "Asleep exceeds in-bed",
                int((sleep_raw.TotalMinutesAsleep > sleep_raw.TotalTimeInBed).sum()),
                "Checked",
                "Reject impossible records if present",
            ],
            [
                "Users with all 31 activity dates",
                int((u.days_logged == 31).sum()),
                "Review",
                "Unequal observation opportunity",
            ],
            [
                "Wide format outside target dates",
                int(
                    read(
                        "SELECT COUNT(*) n FROM minuteStepsWide WHERE ActivityHour>='2016-05-13'"
                    ).iloc[0, 0]
                ),
                "Review",
                "Wide files are not identical-coverage substitutes",
            ],
            [
                "Distance and intensity units",
                None,
                "Unresolved",
                "No embedded unit dictionary; raw scores only",
            ],
            [
                "Demographic fields",
                0,
                "Limitation",
                "No age, sex, height or profession",
            ],
        ],
        columns=["check", "count", "status", "interpretation"],
    )
    record(
        "Repeated user-days",
        "Aggregate user features and attach personas",
        d.shape,
        u.shape,
        "One observation per user for clustering and inference",
    )
    record(
        "Calendar alignment",
        "Join sleep to exact adjacent activity dates",
        s.shape,
        pairs.shape,
        "Left joins preserve sleep days; unmatched activity remains missing",
    )
    record(
        "Incomplete user-weeks",
        "Aggregate complete study windows",
        d.shape,
        weekly.shape,
        "Exclude final 3-day fragment; flags require seven retained days",
    )
    record(
        "Sparse overlapping sensors",
        "Join hourly HR, intensity and raw METs",
        hr.shape,
        hr_join.shape,
        "Inner one-to-one joins; retain only overlapping hours on proxy-valid activity dates",
    )
    cleaning = pd.DataFrame(log)
    tables = dict(
        clean_daily_activity=d,
        flagged_daily_activity=flagged,
        clean_sleep=s,
        clean_weight=w,
        user_summary=u,
        hourly_activity=hour,
        hr_hourly=hr,
        hr_bands=bands,
        hr_intensity_join=hr_join,
        met_hourly=met,
        resting_proxy=resting,
        minute_sleep_logs=episodes,
        sleep_activity_pairs=pairs,
        weekly_activity=weekly,
        source_inventory=inventory,
        column_audit=columns,
        cleaning_log=cleaning,
        quality_scorecard=quality,
        threshold_sensitivity=sensitivity,
        redundancy_checks=redundancy,
        cluster_selection=scores,
        cluster_profiles=profile,
        statistical_tests=tests,
        sleep_lag_statistics=lag_stats,
        reconciliation=recon,
    )
    for name, frame in tables.items():
        save_frame(frame, name, base)
    summary = {
        **metrics,
        "raw_mean_steps": raw.TotalSteps.mean(),
        "excluded_days": len(raw) - len(d),
        "zero_step_days": int((raw.TotalSteps == 0).sum()),
        "full_sedentary_days": int((raw.SedentaryMinutes == 1440).sum()),
        "sleep_users": s.Id.nunique(),
        "hr_users": hr.Id.nunique(),
        "weight_users": w.Id.nunique(),
        "sleep_under7_pct": 100 * (s.TotalMinutesAsleep < 420).mean(),
        "sleep_efficiency_pct": 100 * s.sleep_efficiency.mean(),
        "mean_in_bed_gap": s.in_bed_gap.mean(),
        "manual_logs": int(w.IsManualReport.sum()),
        "missing_fat": int(w.Fat.isna().sum()),
        "split_sleep_days": int((s.TotalSleepRecords > 1).sum()),
        "full31_users": int((u.days_logged == 31).sum()),
        "min_logged_days": int(u.days_logged.min()),
        "best_k": best_k,
        "silhouette": scores.silhouette.max(),
        "min_seed_ari": min(stability),
        "weekend_user_gap": dif.mean(),
        "weekend_gap_ci": np.percentile(bootstrap, [2.5, 97.5]).tolist(),
        "peak_hour": int(hour.groupby("hour").StepTotal.mean().idxmax()),
        "peak_steps": hour.groupby("hour").StepTotal.mean().max(),
        "who_eligible": int(weekly.who_proxy.notna().sum()),
        "who_meeting": int(weekly.who_proxy.sum()),
        "moderate_only_meeting": int(weekly.moderate_only_flag.sum()),
        "step_under7500_pct": 100 * (d.TotalSteps < 7500).mean(),
        "light_share_active": 100
        * d.LightlyActiveMinutes.sum()
        / d.active_minutes.sum(),
    }
    (base / "processed/summary.json").write_text(
        json.dumps(summary, indent=2, default=lambda x: x.item())
    )
    con.close()
    return dict(
        base=base,
        raw=raw,
        d=d,
        s=s,
        w=w,
        u=u,
        hour=hour,
        hr=hr,
        bands=bands,
        hr_join=hr_join,
        met=met,
        resting=resting,
        episodes=episodes,
        pairs=pairs,
        weekly=weekly,
        inventory=inventory,
        columns=columns,
        quality=quality,
        cleaning=cleaning,
        sensitivity=sensitivity,
        redundancy=redundancy,
        scores=scores,
        profile=profile,
        tests=tests,
        lag_stats=lag_stats,
        recon=recon,
        summary=summary,
    )


def plot_chart(number: int, data: dict) -> None:
    """Render and save one distinct static analytical view; all labels include units."""
    import matplotlib.pyplot as plt
    import seaborn as sns
    from sklearn.decomposition import PCA

    d, s, w, u, h = [data[k] for k in ["d", "s", "w", "u", "hour"]]
    summary = data["summary"]
    sns.set_theme(style="whitegrid", palette=PALETTE, font_scale=1.0)
    plt.rcParams.update(
        {
            "figure.dpi": 110,
            "savefig.dpi": 160,
            "axes.spines.top": False,
            "axes.spines.right": False,
            "axes.titleweight": "bold",
            "font.family": "DejaVu Sans",
        }
    )
    fig, ax = plt.subplots(figsize=(10, 5.8))
    title = ""
    if number == 1:
        values = [
            d.Id.nunique(),
            s.Id.nunique(),
            data["hr"].Id.nunique(),
            w.Id.nunique(),
        ]
        ax.barh(
            ["Activity", "Sleep", "Heart rate", "Weight"],
            values,
            color=PALETTE[:4],
            height=0.65,
        )
        ax.invert_yaxis()
        ax.set(xlabel="Distinct users (of 33 activity users)", xlim=(0, 37))
        for i, v in enumerate(values):
            ax.text(v + 0.4, i, f"{v} / 33", va="center")
        title = "Weight logging reaches only 8 of 33 activity users"
    elif number == 2:
        a = data["columns"]
        a = a[a.null_rows > 0]
        ax.bar(a.column_name, a.null_rows, color=PALETTE[4])
        ax.set(ylabel="Missing cells (count)", xlabel="Field with missing values")
        for i, v in enumerate(a.null_rows):
            ax.text(i, v + 1, str(v), ha="center")
        title = (
            f'{summary["missing_fat"]} of 67 weight records omit body-fat percentage'
        )
    elif number == 3:
        a = data["sensitivity"]
        ax.plot(a.minimum_steps, a.mean_steps, "o-", color=PALETTE[0])
        for _, r in a.iterrows():
            ax.annotate(
                f"{int(r.days)} retained days",
                (r.minimum_steps, r.mean_steps),
                xytext=(0, 10),
                textcoords="offset points",
                ha="center",
                fontsize=9,
            )
        ax.margins(x=0.15, y=0.3)
        ax.set(
            xlabel="Minimum steps for quality proxy (steps/day)",
            ylabel="Mean retained steps/day",
        )
        title = "Higher wear-proxy thresholds selectively raise the activity baseline"
    elif number == 4:
        sns.histplot(d.TotalSteps, bins=28, kde=True, ax=ax, color=PALETTE[0])
        ax.axvline(
            d.TotalSteps.median(),
            color=PALETTE[4],
            ls="--",
            label=f"Median {d.TotalSteps.median():,.0f}",
        )
        ax.set(xlabel="Steps per retained user-day", ylabel="User-days (count)")
        ax.legend()
        title = f'{summary["step_under7500_pct"]:.1f}% of retained days stay below 7,500 steps'
    elif number == 5:
        sns.ecdfplot(data=u, x="valid_days", ax=ax, color=PALETTE[0])
        ax.set(
            xlabel="Retained days per user (of 31)", ylabel="Cumulative share of users"
        )
        title = f"Users contribute {u.valid_days.min()} to {u.valid_days.max()} retained activity days"
    elif number == 6:
        sns.boxplot(
            data=d,
            x="steps_category",
            y="Calories",
            color=PALETTE[0],
            ax=ax,
            showfliers=False,
        )
        ax.set(
            xlabel="Descriptive daily step tier", ylabel="Total daily calories (kcal)"
        )
        ax.tick_params(axis="x", rotation=15)
        title = "Total calorie distributions overlap across step tiers"
    elif number == 7:
        sns.violinplot(
            data=d,
            x="weekend",
            y="active_minutes",
            inner="quart",
            color=PALETTE[2],
            cut=0,
            ax=ax,
        )
        ax.set(
            xticks=[0, 1],
            xticklabels=["Weekday", "Weekend"],
            xlabel="",
            ylabel="Classified active minutes/day",
        )
        title = "Weekday and weekend activity have substantial within-group variation"
    elif number == 8:
        sns.stripplot(
            data=s,
            x="TotalSleepRecords",
            y="sleep_hours",
            jitter=0.2,
            alpha=0.45,
            color=PALETTE[3],
            ax=ax,
        )
        ax.axhspan(7, 9, color=PALETTE[2], alpha=0.1)
        ax.set(
            xlabel="Sleep records on a reported day (count)",
            ylabel="Recorded sleep (hours/day)",
        )
        title = f'{summary["split_sleep_days"]} sleep days combine more than one record'
    elif number == 9:
        cols = [
            "mean_steps",
            "mean_active",
            "mean_calories",
            "mean_sleep",
            "engagement_score",
        ]
        corr = u[cols].corr(method="spearman")
        labels = ["Steps", "Active min", "Calories", "Sleep min", "Engagement"]
        sns.heatmap(
            corr,
            annot=True,
            fmt=".2f",
            vmin=-1,
            vmax=1,
            cmap="vlag",
            xticklabels=labels,
            yticklabels=labels,
            ax=ax,
        )
        ax.tick_params(axis="x", rotation=20)
        title = "User-level associations separate typical behaviour from repeated daily records"
    elif number == 10:
        b = ax.hexbin(d.TotalSteps, d.Calories, gridsize=27, mincnt=1, cmap="Blues")
        fig.colorbar(b, ax=ax, label="Retained user-days per hexagon")
        ax.set(xlabel="Steps/day", ylabel="Total daily calories (kcal)")
        title = "Similar step totals correspond to different daily calorie estimates"
    elif number == 11:
        sns.regplot(
            data=u,
            x="mean_steps",
            y="mean_calories",
            seed=SEED,
            n_boot=1000,
            ax=ax,
            scatter_kws={"s": 50},
            line_kws={"color": PALETTE[4]},
        )
        ax.set(
            xlabel="User mean steps/day", ylabel="User mean total calories/day (kcal)"
        )
        title = (
            "Between-user calorie association is descriptive, with a 95% bootstrap band"
        )
    elif number == 12:
        a = d.groupby("weekday").TotalSteps.mean().reindex(DAY_ORDER)
        ax.hlines(a.index, 0, a, color=PALETTE[0], lw=2)
        ax.scatter(a, a.index, s=80, color=PALETTE[0])
        ax.invert_yaxis()
        for i, v in enumerate(a):
            ax.text(v + 100, i, f"{v:,.0f}", va="center")
        ax.set(xlabel="Mean steps per retained user-day", xlim=(0, a.max() * 1.18))
        title = f"{a.idxmax()} has the highest pooled mean at {a.max():,.0f} steps"
    elif number == 13:
        a = (
            d.groupby(["Id", "weekend"])
            .TotalSteps.mean()
            .unstack()
            .dropna()
            .sort_values(0)
        )
        for i, (_, r) in enumerate(a.iterrows()):
            ax.plot([r[0], r[1]], [i, i], color="#B4BCC4", lw=1)
        ax.scatter(a[0], range(len(a)), label="Weekday", color=PALETTE[0], s=25)
        ax.scatter(a[1], range(len(a)), label="Weekend", color=PALETTE[1], s=25)
        ax.set(
            yticks=[],
            ylabel=f"{len(a)} paired users, sorted by weekday mean",
            xlabel="User mean steps/day",
        )
        ax.legend()
        title = f'The average paired weekend gap is {summary["weekend_user_gap"]:+,.0f} steps'
    elif number == 14:
        a = h.pivot_table(
            index="weekday", columns="hour", values="StepTotal", aggfunc="mean"
        ).reindex(DAY_ORDER)
        sns.heatmap(
            a, cmap="YlGnBu", ax=ax, cbar_kws={"label": "Mean steps / observed hour"}
        )
        ax.set(xlabel="Hour of day (source local time)", ylabel="")
        title = f'Observed activity peaks at {summary["peak_hour"]:02d}:00 overall'
    elif number == 15:
        a = d.groupby("date").TotalSteps.mean().to_frame("steps")
        a["week"] = (a.index - pd.Timestamp("2016-04-11")).days // 7
        a["weekday"] = a.index.dayofweek
        mat = a.pivot(index="week", columns="weekday", values="steps").reindex(
            columns=range(7)
        )
        sns.heatmap(
            mat,
            annot=True,
            fmt=".0f",
            cmap="YlGnBu",
            xticklabels=[v[:3] for v in DAY_ORDER],
            ax=ax,
            cbar_kws={"label": "Mean steps / retained day"},
        )
        ax.set(xlabel="", ylabel="Calendar week from Apr 11 (zero-based)")
        title = "Calendar coverage makes the partial final week visible"
    elif number == 16:
        cols = ["LightlyActiveMinutes", "FairlyActiveMinutes", "VeryActiveMinutes"]
        a = d.groupby("date")[cols].sum()
        a = a.div(a.sum(axis=1), axis=0) * 100
        ax.stackplot(
            a.index,
            *[a[c] for c in cols],
            labels=["Light", "Fairly active", "Very active"],
            colors=PALETTE[:3],
        )
        ax.legend(loc="upper left", ncol=3)
        ax.set(
            ylabel="Share of classified active minutes (%)",
            xlabel="Date in 2016",
            ylim=(0, 115),
        )
        fig.autofmt_xdate()
        title = f'Light activity contributes {summary["light_share_active"]:.1f}% of active minutes'
    elif number == 17:
        fig.clear()
        axes = fig.subplots(2, 1, sharex=True, gridspec_kw={"height_ratios": [3, 1]})
        ax = axes[0]
        a = d.groupby("date").agg(steps=("TotalSteps", "mean"), users=("Id", "nunique"))
        ax.plot(a.index, a.steps, color="#A6B5C2", label="Daily mean")
        ax.plot(
            a.index,
            a.steps.rolling(7, min_periods=1).mean(),
            color=PALETTE[0],
            lw=2,
            label="Trailing 7-calendar-day mean",
        )
        ax.legend(fontsize=9)
        ax.set(ylabel="Mean steps/day")
        axes[1].bar(a.index, a.users, color=PALETTE[2])
        axes[1].set(ylabel="Users", xlabel="Date in 2016")
        fig.autofmt_xdate()
        title = "Changing participant coverage complicates apparent month-long trends"
    elif number == 18:
        a = pd.crosstab(s.Id, s.sleep_band, normalize="index").sort_values("<7 h") * 100
        a.plot.bar(
            stacked=True, ax=ax, color=[PALETTE[1], PALETTE[2], PALETTE[3]], width=0.9
        )
        ax.set(
            xticklabels=[],
            xlabel="Sleep users sorted by share below 7 hours",
            ylabel="Share of recorded sleep days (%)",
        )
        ax.legend(
            title="Duration", ncol=3, loc="upper center", bbox_to_anchor=(0.5, 1.15)
        )
        title = f'{summary["sleep_under7_pct"]:.1f}% of recorded sleep days fall below 7 hours'
    elif number == 19:
        ax.scatter(
            s.sleep_hours,
            s.sleep_efficiency * 100,
            s=s.TotalSleepRecords * 22,
            alpha=0.4,
            color=PALETTE[3],
        )
        ax.axvspan(7, 9, color=PALETTE[2], alpha=0.08)
        ax.set(
            xlabel="Recorded sleep (hours/day)", ylabel="Recorded sleep efficiency (%)"
        )
        title = f'Time in bed exceeds sleep by {summary["mean_in_bed_gap"]:.0f} minutes on average'
    elif number == 20:
        a = data["lag_stats"]
        ax.errorbar(
            a.median_within_user_rho,
            a.alignment,
            xerr=[
                a.median_within_user_rho - a.ci_low,
                a.ci_high - a.median_within_user_rho,
            ],
            fmt="o",
            capsize=5,
            color=PALETTE[0],
        )
        ax.axvline(0, color="#666", ls="--")
        ax.set(
            xlabel="Median within-user Spearman rho (95% user-bootstrap CI)",
            ylabel="Activity date relative to sleep label",
        )
        title = "Adjacent-day sleep associations are uncertain within this small panel"
    elif number == 21:
        a = (
            data["bands"]
            .pivot(index="Id", columns="bpm_band", values="observed_seconds")
            .fillna(0)
        )
        a = a.reindex(columns=["<60", "60-99", "100-139", "140+"])
        a = a.div(a.sum(axis=1), axis=0) * 100
        a.plot.barh(stacked=True, ax=ax, color=PALETTE[:4])
        ax.set(
            yticklabels=[],
            ylabel="14 heart-rate users",
            xlabel="Share of observed interval time (%)",
        )
        ax.legend(
            title="Descriptive bpm band",
            ncol=4,
            loc="upper center",
            bbox_to_anchor=(0.5, 1.18),
        )
        title = "Heart-rate time shares exclude gaps longer than 60 seconds"
    elif number == 22:
        a = data["resting"].sort_values("night_p10_bpm")
        ax.stem(
            range(len(a)),
            a.night_p10_bpm,
            bottom=30,
            linefmt="C0-",
            markerfmt="C0o",
            basefmt=" ",
        )
        ax.set(
            xlabel="Users ranked by overnight proxy",
            ylabel="10th percentile of overnight hourly mean HR (bpm)",
            ylim=(30, max(a.night_p10_bpm) + 8),
        )
        title = (
            "Overnight heart-rate proxies describe only users with night observations"
        )
    elif number == 23:
        a = data["hr_join"]
        sns.kdeplot(
            data=a,
            x="mean_raw_mets",
            y="mean_bpm",
            levels=7,
            fill=True,
            cmap="Blues",
            ax=ax,
        )
        ax.set(
            xlabel="Hourly mean METs field (raw export units)",
            ylabel="Hourly mean heart rate (bpm)",
        )
        title = f"{len(a):,} matching user-hours link heart rate to raw exertion scores"
    elif number == 24:
        a = w.groupby("Id").size().sort_values(ascending=False)
        ax.bar(range(len(a)), a, color=PALETTE[0])
        other = ax.twinx()
        other.plot(range(len(a)), 100 * a.cumsum() / a.sum(), "o-", color=PALETTE[4])
        other.set(ylabel="Cumulative share of weight logs (%)", ylim=(0, 105))
        ax.set(
            xticks=range(len(a)),
            xticklabels=[f"W{i+1}" for i in range(len(a))],
            xlabel="Weight users ranked by log count",
            ylabel="Weight logs (count)",
        )
        title = f"Top two weight loggers contribute {100*a.iloc[:2].sum()/a.sum():.1f}% of records"
    elif number == 25:
        ids = w.groupby("Id").size().sort_values(ascending=False).index
        for i, uid in enumerate(ids):
            a = w[w.Id == uid]
            for manual, color in [(0, PALETTE[0]), (1, PALETTE[1])]:
                sub = a[a.IsManualReport == manual]
                ax.scatter(
                    sub.date,
                    [i] * len(sub),
                    marker="|",
                    s=220,
                    color=color,
                    label=("Automatic", "Manual")[manual] if i == 0 else None,
                )
        from matplotlib.lines import Line2D

        ax.legend(
            handles=[
                Line2D(
                    [0], [0], color=PALETTE[0], marker="|", ls="", label="Automatic"
                ),
                Line2D([0], [0], color=PALETTE[1], marker="|", ls="", label="Manual"),
            ]
        )
        ax.set(
            yticks=range(len(ids)),
            yticklabels=[f"W{i+1}" for i in range(len(ids))],
            xlabel="Date in 2016",
            ylabel="Weight users ranked by logging frequency",
        )
        fig.autofmt_xdate()
        title = f'{summary["manual_logs"]} of 67 weight logs are manual'
    elif number == 26:
        fig.clear()
        axes = fig.subplots(1, 2)
        a = data["scores"]
        axes[0].plot(a.k, a.inertia, "o-", color=PALETTE[0])
        axes[0].set(xlabel="k clusters", ylabel="Within-cluster sum of squares")
        axes[1].plot(a.k, a.silhouette, "s-", color=PALETTE[2])
        axes[1].axvline(summary["best_k"], color=PALETTE[4], ls="--")
        axes[1].set(xlabel="k clusters", ylabel="Mean silhouette score")
        title = (
            f'k={summary["best_k"]} maximizes silhouette at {summary["silhouette"]:.2f}'
        )
    elif number == 27:
        fig.clear()
        ax = fig.add_subplot(111, projection="polar")
        cols = ["mean_steps", "mean_active_share", "engagement_score"]
        p = data["profile"]
        v = p[cols].copy()
        v = (v - u[cols].min()) / (u[cols].max() - u[cols].min())
        angles = np.linspace(0, 2 * np.pi, 3, endpoint=False).tolist()
        angles += angles[:1]
        for i, (_, r) in enumerate(v.iterrows()):
            values = r.tolist() + r.tolist()[:1]
            ax.plot(angles, values, color=PALETTE[i], label=p.iloc[i].persona)
            ax.fill(angles, values, color=PALETTE[i], alpha=0.07)
        ax.set_xticks(angles[:-1], ["Steps", "Active share", "Engagement"])
        ax.set_ylim(0, 1)
        ax.legend(loc="upper left", bbox_to_anchor=(1.1, 1), fontsize=9)
        title = (
            "Personas differ in activity and recording consistency (min-max profile)"
        )
    elif number == 28:
        a = u.dropna(subset=["cluster"])
        cols = ["mean_steps", "mean_active_share", "engagement_score"]
        x = StandardScaler().fit_transform(a[cols])
        pca = PCA(n_components=2).fit(x)
        xy = pca.transform(x)
        for i, name in enumerate(sorted(a.persona.unique())):
            mask = (a.persona == name).to_numpy()
            ax.scatter(xy[mask, 0], xy[mask, 1], s=65, color=PALETTE[i], label=name)
        ax.set(
            xlabel=f"PC1 ({100*pca.explained_variance_ratio_[0]:.1f}% variance)",
            ylabel=f"PC2 ({100*pca.explained_variance_ratio_[1]:.1f}% variance)",
        )
        ax.legend(fontsize=9)
        title = (
            "Clustering describes this sample; the personas need external validation"
        )
    elif number == 29:
        stats.probplot(u.mean_steps.dropna(), dist="norm", plot=ax)
        ax.get_lines()[0].set_color(PALETTE[0])
        ax.get_lines()[1].set_color(PALETTE[4])
        ax.set(
            xlabel="Theoretical normal quantile", ylabel="Ordered user mean steps/day"
        )
        title = "Normality diagnostics use 33 independent user summaries"
    elif number == 30:
        a = (
            d.merge(u[["Id", "rule_segment"]], on="Id")
            .groupby(["study_week", "rule_segment"])
            .TotalSteps.mean()
            .unstack()
        )
        rank = a.rank(axis=1, ascending=False)
        for i, c in enumerate(rank):
            ax.plot(rank.index, rank[c], marker="o", lw=2, color=PALETTE[i], label=c)
        ax.invert_yaxis()
        ax.set(
            xticks=rank.index,
            xlabel="Study week (week 5 is a 3-day fragment)",
            ylabel="Rank of segment mean steps (1 = highest)",
            yticks=[1, 2, 3],
        )
        ax.legend()
        title = (
            "Rule-based segments provide a stable, interpretable campaign vocabulary"
        )
    else:
        raise ValueError(number)
    fig.suptitle(
        f"{number:02d}  {title}",
        x=0.06,
        y=0.99,
        ha="left",
        fontsize=13,
        fontweight="bold",
        wrap=True,
    )
    fig.text(
        0.06,
        0.015,
        "Source: supplied Fitbit / MTurk export, 2016. Descriptive observational analysis; see notebook denominators.",
        fontsize=8,
        color="#53616E",
    )
    fig.tight_layout(rect=(0.02, 0.05, 0.98, 0.94))
    fig.savefig(
        data["base"] / "charts" / f"chart_{number:02d}.png", bbox_inches="tight"
    )
    plt.show()
    plt.close(fig)
