-- Bellabeat / Fitbit | SQLite 3.25+ | run after load_csv_to_sqlite.py
-- Dates are parsed in Python with %m/%d/%Y or %m/%d/%Y %I:%M:%S %p.
-- SQLite receives ISO TEXT; identifiers remain 64-bit INTEGER.
-- PostgreSQL: use EXTRACT/date_trunc; MySQL: DAYOFWEEK/DATE_FORMAT;
-- SQL Server: DATEPART/DATEADD. Replace SQLite julianday/strftime accordingly.
-- Wear quality is a proxy, not sensor-confirmed wear: steps >=100, sedentary<1440.
-- Exact duplicates removed; invalid sleep and nonpositive weight excluded.
-- HR bands are descriptive bpm bands, NOT age-based clinical exercise zones.
-- Re-running safely rebuilds only derived tables/views, leaving imported data intact.


-- ===========================================================================
-- 1. SCHEMA, TABLES AND INDEXES
-- ===========================================================================

-- QUERY: schema
-- Purpose: Inspect imported schema
-- Business question: Which grains can be joined safely?
-- Expected output: Objects and definitions
SELECT type,name,tbl_name,sql FROM sqlite_master WHERE name NOT LIKE 'sqlite_%' ORDER BY type,name;


-- ===========================================================================
-- 2. DATA INTEGRITY
-- ===========================================================================

-- QUERY: inventory
-- Purpose: Audit every source
-- Business question: How broad and complete are the data?
-- Expected output: 18 source rows
SELECT * FROM source_inventory ORDER BY table_name;

-- QUERY: missing_invalid
-- Purpose: Inspect column-level missing/negative values
-- Business question: Which fields require caution?
-- Expected output: One row per source column
SELECT * FROM column_audit ORDER BY table_name,column_name;

-- QUERY: activity_quality
-- Purpose: Quantify wear-quality and impossible values
-- Business question: How much raw activity is suspect?
-- Expected output: One summary row
SELECT COUNT(*) raw_rows,COUNT(DISTINCT Id) users,
SUM(TotalSteps=0) zero_steps,SUM(TotalSteps<100) near_zero_steps,
SUM(SedentaryMinutes=1440) full_sedentary,
SUM(SedentaryMinutes>=1440 OR TotalSteps<100) excluded_days,
SUM(VeryActiveMinutes+FairlyActiveMinutes+LightlyActiveMinutes+SedentaryMinutes>1440) over_24h,
SUM(Calories=0) zero_calories FROM dailyActivity;

-- QUERY: overlap
-- Purpose: Count modality adoption
-- Business question: How many activity users have additional signals?
-- Expected output: One row per modality
SELECT 'sleep' modality,COUNT(DISTINCT s.Id) users FROM sleepDay s JOIN dailyActivity a ON a.Id=s.Id
UNION ALL SELECT 'weight',COUNT(DISTINCT w.Id) FROM weightLogInfo w JOIN dailyActivity a ON a.Id=w.Id
UNION ALL SELECT 'heart_rate',COUNT(DISTINCT h.Id) FROM (SELECT DISTINCT Id FROM heartrate_seconds) h JOIN dailyActivity a ON a.Id=h.Id;


-- ===========================================================================
-- 3. CLEANING LAYER
-- ===========================================================================

-- QUERY: drop_clean_daily_activity
-- Purpose: Refresh derived view
-- Business question: Can analysis be reproduced?
-- Expected output: No result
DROP VIEW IF EXISTS clean_daily_activity;

-- QUERY: drop_clean_sleep
-- Purpose: Refresh derived view
-- Business question: Can analysis be reproduced?
-- Expected output: No result
DROP VIEW IF EXISTS clean_sleep;

-- QUERY: drop_clean_weight
-- Purpose: Refresh derived view
-- Business question: Can analysis be reproduced?
-- Expected output: No result
DROP VIEW IF EXISTS clean_weight;

-- QUERY: drop_hourly_activity
-- Purpose: Refresh derived view
-- Business question: Can analysis be reproduced?
-- Expected output: No result
DROP VIEW IF EXISTS hourly_activity;

-- QUERY: drop_user_summary
-- Purpose: Refresh derived view
-- Business question: Can analysis be reproduced?
-- Expected output: No result
DROP VIEW IF EXISTS user_summary;

-- QUERY: drop_weekly_activity
-- Purpose: Refresh derived view
-- Business question: Can analysis be reproduced?
-- Expected output: No result
DROP VIEW IF EXISTS weekly_activity;

-- QUERY: create_daily
-- Purpose: Apply wear proxy and features
-- Business question: What is a credible activity day?
-- Expected output: Derived daily view
CREATE VIEW clean_daily_activity AS
SELECT DISTINCT *,
 VeryActiveMinutes+FairlyActiveMinutes+LightlyActiveMinutes AS active_minutes,
 (VeryActiveMinutes+FairlyActiveMinutes+LightlyActiveMinutes)*1.0/
 NULLIF(VeryActiveMinutes+FairlyActiveMinutes+LightlyActiveMinutes+SedentaryMinutes,0) active_share,
 FairlyActiveMinutes+2*VeryActiveMinutes moderate_equivalent,
 CASE WHEN CAST(strftime('%w',ActivityDate) AS INTEGER) IN (0,6) THEN 1 ELSE 0 END weekend,
 CAST(strftime('%w',ActivityDate) AS INTEGER) weekday_sunday_zero,
 Calories*1.0/NULLIF(TotalSteps,0) calories_per_step,
 CASE WHEN TotalSteps<5000 THEN 'Sedentary' WHEN TotalSteps<7500 THEN 'Low active'
 WHEN TotalSteps<10000 THEN 'Somewhat active' WHEN TotalSteps<12500 THEN 'Active'
 ELSE 'Highly active' END steps_category
FROM dailyActivity WHERE TotalSteps>=100 AND SedentaryMinutes<1440;

-- QUERY: create_sleep
-- Purpose: Deduplicate and validate sleep
-- Business question: What is reliable recorded sleep?
-- Expected output: Derived sleep view
CREATE VIEW clean_sleep AS SELECT DISTINCT *,substr(SleepDay,1,10) sleep_date,
TotalMinutesAsleep*1.0/NULLIF(TotalTimeInBed,0) sleep_efficiency,
TotalTimeInBed-TotalMinutesAsleep in_bed_gap
FROM sleepDay WHERE TotalMinutesAsleep>0 AND TotalTimeInBed>=TotalMinutesAsleep AND TotalTimeInBed<=1440;

-- QUERY: create_weight
-- Purpose: Retain valid logs without imputing Fat
-- Business question: How is weight logged?
-- Expected output: Derived weight view
CREATE VIEW clean_weight AS SELECT DISTINCT *,substr(Date,1,10) weight_date
FROM weightLogInfo WHERE WeightKg>0 AND BMI>0;

-- QUERY: create_hourly
-- Purpose: Join matching user-hour keys
-- Business question: When does recorded activity peak?
-- Expected output: One row per available valid-day hour
CREATE VIEW hourly_activity AS SELECT s.Id,s.ActivityHour,substr(s.ActivityHour,1,10) activity_date,
CAST(strftime('%H',s.ActivityHour) AS INTEGER) hour,s.StepTotal,c.Calories,i.TotalIntensity,i.AverageIntensity
FROM hourlySteps s JOIN clean_daily_activity d ON s.Id=d.Id AND substr(s.ActivityHour,1,10)=d.ActivityDate
LEFT JOIN hourlyCalories c ON s.Id=c.Id AND s.ActivityHour=c.ActivityHour
LEFT JOIN hourlyIntensities i ON s.Id=i.Id AND s.ActivityHour=i.ActivityHour;

-- QUERY: create_users
-- Purpose: Separate logging coverage from activity level
-- Business question: Who needs onboarding versus habit support?
-- Expected output: One row per activity user
CREATE VIEW user_summary AS
WITH logs AS (SELECT Id,COUNT(DISTINCT ActivityDate) days_logged,MIN(ActivityDate) first_date,MAX(ActivityDate) last_date FROM dailyActivity GROUP BY Id),
v AS (SELECT Id,COUNT(*) valid_days,AVG(TotalSteps) mean_steps,AVG(active_minutes) mean_active,AVG(SedentaryMinutes) mean_sedentary,AVG(Calories) mean_calories FROM clean_daily_activity GROUP BY Id)
SELECT l.*,COALESCE(v.valid_days,0) valid_days,v.mean_steps,v.mean_active,v.mean_sedentary,v.mean_calories,
100.0*COALESCE(v.valid_days,0)/31 engagement_score,
CASE WHEN COALESCE(v.valid_days,0)<21 THEN 'Reconnect' WHEN v.mean_steps<7500 THEN 'Build routine' ELSE 'Keep momentum' END rule_segment
FROM logs l LEFT JOIN v ON l.Id=v.Id;

-- QUERY: create_weekly
-- Purpose: Use four complete study weeks; exclude final 3-day fragment
-- Business question: Which observed weeks reach the activity benchmark?
-- Expected output: User-week counts and cautious flags
CREATE VIEW weekly_activity AS
SELECT Id,CAST((julianday(ActivityDate)-julianday('2016-04-12'))/7 AS INTEGER)+1 study_week,
COUNT(*) valid_days,SUM(FairlyActiveMinutes) moderate_minutes,SUM(moderate_equivalent) moderate_equivalent,
CASE WHEN COUNT(*)=7 THEN CASE WHEN SUM(moderate_equivalent)>=150 THEN 1 ELSE 0 END ELSE NULL END who_proxy,
CASE WHEN COUNT(*)=7 THEN CASE WHEN SUM(FairlyActiveMinutes)>=150 THEN 1 ELSE 0 END ELSE NULL END moderate_only_flag
FROM clean_daily_activity WHERE ActivityDate<'2016-05-10' GROUP BY Id,study_week;

-- QUERY: drop_hr_hourly
-- Purpose: Refresh aggregate
-- Business question: Can high-volume data stay bounded?
-- Expected output: No result
DROP TABLE IF EXISTS hr_hourly;

-- QUERY: drop_hr_bands
-- Purpose: Refresh aggregate
-- Business question: Can high-volume data stay bounded?
-- Expected output: No result
DROP TABLE IF EXISTS hr_bands;

-- QUERY: drop_met_hourly
-- Purpose: Refresh aggregate
-- Business question: Can high-volume data stay bounded?
-- Expected output: No result
DROP TABLE IF EXISTS met_hourly;

-- QUERY: drop_minute_sleep_logs
-- Purpose: Refresh aggregate
-- Business question: Can high-volume data stay bounded?
-- Expected output: No result
DROP TABLE IF EXISTS minute_sleep_logs;

-- QUERY: create_hr_hours
-- Purpose: Aggregate irregular HR readings
-- Business question: What does observed hourly heart rate show?
-- Expected output: One row per HR user-hour
CREATE TABLE hr_hourly AS SELECT Id,substr(Time,1,13)||':00:00' ActivityHour,
COUNT(*) samples,AVG(Value) mean_bpm,MIN(Value) min_bpm,MAX(Value) max_bpm FROM heartrate_seconds
WHERE Value BETWEEN 30 AND 220 GROUP BY Id,substr(Time,1,13);

-- QUERY: hr_index
-- Purpose: Index HR aggregate
-- Business question: Can joins avoid repeated scans?
-- Expected output: No result
CREATE INDEX ix_hr_hour ON hr_hourly(Id,ActivityHour);

-- QUERY: create_hr_bands
-- Purpose: Weight by observed interval, omit gaps longer than 60 sec
-- Business question: How much observed time falls in each bpm band?
-- Expected output: User-band seconds, samples and rejected gaps
CREATE TABLE hr_bands AS WITH gaps AS (
SELECT Id,Time,Value,(julianday(LEAD(Time) OVER(PARTITION BY Id ORDER BY Time))-julianday(Time))*86400 seconds FROM heartrate_seconds)
SELECT Id,CASE WHEN Value<60 THEN '<60' WHEN Value<100 THEN '60-99' WHEN Value<140 THEN '100-139' ELSE '140+' END bpm_band,
COUNT(*) samples,SUM(CASE WHEN seconds>0 AND seconds<=60.001 THEN ROUND(seconds) ELSE 0 END) observed_seconds,
SUM(CASE WHEN seconds>60.001 THEN 1 ELSE 0 END) long_gaps
FROM gaps WHERE Value BETWEEN 30 AND 220 GROUP BY Id,bpm_band;

-- QUERY: create_mets
-- Purpose: Aggregate METs without undocumented scaling
-- Business question: How does raw exertion relate to heart rate?
-- Expected output: One row per user-hour with raw MET score
CREATE TABLE met_hourly AS SELECT Id,substr(ActivityMinute,1,13)||':00:00' ActivityHour,
AVG(METs) mean_raw_mets,COUNT(*) minutes FROM minuteMETsNarrow GROUP BY Id,substr(ActivityMinute,1,13);

-- QUERY: create_sleep_logs
-- Purpose: Preserve sleep episode boundaries and unknown state labels
-- Business question: Can sleep latency be identified?
-- Expected output: One row per episode; codes remain raw
CREATE TABLE minute_sleep_logs AS SELECT Id,logId,MIN(date) start_time,MAX(date) end_time,COUNT(*) recorded_minutes,
SUM(value=1) code_1_minutes,SUM(value=2) code_2_minutes,SUM(value=3) code_3_minutes
FROM (SELECT DISTINCT * FROM minuteSleep) GROUP BY Id,logId;


-- ===========================================================================
-- 4. DESCRIPTIVE EDA
-- ===========================================================================

-- QUERY: descriptive
-- Purpose: Summarize clean daily measures
-- Business question: What is typical activity?
-- Expected output: One row with mean, median, range
WITH ranked AS (SELECT TotalSteps,ROW_NUMBER() OVER(ORDER BY TotalSteps) rn,COUNT(*) OVER() n FROM clean_daily_activity)
SELECT COUNT(*) valid_days,AVG(TotalSteps) mean_steps,MIN(TotalSteps) min_steps,MAX(TotalSteps) max_steps,
AVG(CASE WHEN rn IN ((n+1)/2,(n+2)/2) THEN TotalSteps END) median_steps FROM ranked;

-- QUERY: step_distribution
-- Purpose: Apply descriptive step tiers
-- Business question: How many retained days are in each tier?
-- Expected output: Five tier counts
SELECT steps_category,COUNT(*) days,AVG(TotalSteps) mean_steps FROM clean_daily_activity GROUP BY steps_category;

-- QUERY: user_quartiles
-- Purpose: Rank users by activity
-- Business question: How wide is between-user variation?
-- Expected output: Users and quartiles
SELECT Id,mean_steps,NTILE(4) OVER(ORDER BY mean_steps) quartile FROM user_summary;


-- ===========================================================================
-- 5. BUSINESS ANALYSIS
-- ===========================================================================

-- QUERY: user_segments
-- Purpose: Answer a business question
-- Business question: Which users need different support?
-- Expected output: Grouped metrics or explicitly keyed analytical rows
SELECT rule_segment,COUNT(*) users,AVG(mean_steps) mean_steps,AVG(engagement_score) engagement FROM user_summary GROUP BY rule_segment;

-- QUERY: weekday_weekend
-- Purpose: Answer a business question
-- Business question: Does the habit change on weekends?
-- Expected output: Grouped metrics or explicitly keyed analytical rows
SELECT weekend,COUNT(*) days,COUNT(DISTINCT Id) users,AVG(TotalSteps) mean_steps FROM clean_daily_activity GROUP BY weekend;

-- QUERY: hourly_peaks
-- Purpose: Answer a business question
-- Business question: When are recorded steps highest?
-- Expected output: Grouped metrics or explicitly keyed analytical rows
SELECT hour,COUNT(*) user_hours,AVG(StepTotal) mean_steps,RANK() OVER(ORDER BY AVG(StepTotal) DESC) peak_rank FROM hourly_activity GROUP BY hour;

-- QUERY: sleep_activity
-- Purpose: Answer a business question
-- Business question: How does recorded sleep align with adjacent dates?
-- Expected output: Grouped metrics or explicitly keyed analytical rows
SELECT s.Id,s.sleep_date,s.TotalMinutesAsleep,s.sleep_efficiency,
a.TotalSteps same_date_steps,p.TotalSteps previous_date_steps,n.TotalSteps next_date_steps
FROM clean_sleep s LEFT JOIN clean_daily_activity a ON a.Id=s.Id AND a.ActivityDate=s.sleep_date
LEFT JOIN clean_daily_activity p ON p.Id=s.Id AND p.ActivityDate=date(s.sleep_date,'-1 day')
LEFT JOIN clean_daily_activity n ON n.Id=s.Id AND n.ActivityDate=date(s.sleep_date,'+1 day');

-- QUERY: calories_intensity
-- Purpose: Answer a business question
-- Business question: Are more active days associated with more total calories?
-- Expected output: Grouped metrics or explicitly keyed analytical rows
SELECT steps_category,COUNT(*) days,AVG(Calories) total_daily_calories,AVG(active_minutes) active_minutes,AVG(VeryActiveMinutes) vigorous_minutes FROM clean_daily_activity GROUP BY steps_category;

-- QUERY: engagement
-- Purpose: Answer a business question
-- Business question: Who records consistently?
-- Expected output: Grouped metrics or explicitly keyed analytical rows
SELECT * FROM user_summary ORDER BY engagement_score DESC;

-- QUERY: weekly_retention
-- Purpose: Answer a business question
-- Business question: How many original users remain observable each study week?
-- Expected output: Grouped metrics or explicitly keyed analytical rows
SELECT CAST((julianday(ActivityDate)-julianday('2016-04-12'))/7 AS INTEGER)+1 study_week,COUNT(DISTINCT Id) observable_users,COUNT(*) valid_days FROM clean_daily_activity GROUP BY study_week;

-- QUERY: who_guideline
-- Purpose: Answer a business question
-- Business question: Which fully observed weeks meet a WHO-inspired proxy?
-- Expected output: Grouped metrics or explicitly keyed analytical rows
SELECT study_week,COUNT(*) observed_user_weeks,SUM(valid_days=7) eligible_weeks,SUM(who_proxy=1) meeting_proxy,SUM(moderate_only_flag=1) moderate_only_meeting FROM weekly_activity GROUP BY study_week;

-- QUERY: heart_rate_zones
-- Purpose: Answer a business question
-- Business question: What are the descriptive HR time bands?
-- Expected output: Grouped metrics or explicitly keyed analytical rows
SELECT bpm_band,SUM(observed_seconds)/3600.0 observed_hours,SUM(samples) readings,SUM(long_gaps) excluded_gaps FROM hr_bands GROUP BY bpm_band;

-- QUERY: weight_behavior
-- Purpose: Answer a business question
-- Business question: Is weight a broadly used feature?
-- Expected output: Grouped metrics or explicitly keyed analytical rows
SELECT Id,COUNT(*) logs,COUNT(DISTINCT weight_date) days,SUM(IsManualReport) manual_logs,SUM(Fat IS NULL) missing_fat,AVG(BMI) mean_recorded_bmi FROM clean_weight GROUP BY Id;

-- QUERY: hr_intensity
-- Purpose: Answer a business question
-- Business question: Do overlapping hours support exertion signals?
-- Expected output: Grouped metrics or explicitly keyed analytical rows
SELECT h.*,a.TotalIntensity,m.mean_raw_mets FROM hr_hourly h
JOIN hourly_activity a ON h.Id=a.Id AND h.ActivityHour=a.ActivityHour
JOIN met_hourly m ON h.Id=m.Id AND h.ActivityHour=m.ActivityHour;


-- ===========================================================================
-- 6. ADVANCED SQL
-- ===========================================================================

-- QUERY: user_rankings
-- Purpose: Compare several rank definitions
-- Business question: Who has the strongest recorded engagement?
-- Expected output: User rankings
SELECT Id,mean_steps,engagement_score,RANK() OVER(ORDER BY mean_steps DESC) step_rank,
DENSE_RANK() OVER(ORDER BY valid_days DESC) coverage_rank,PERCENT_RANK() OVER(ORDER BY mean_steps) step_percentile FROM user_summary;

-- QUERY: rolling_activity
-- Purpose: Use calendar range, not seven available rows
-- Business question: How does activity evolve for each user?
-- Expected output: Daily preceding/following dates and rolling metrics
SELECT Id,ActivityDate,TotalSteps,
LAG(TotalSteps) OVER(PARTITION BY Id ORDER BY ActivityDate) prior_observed_steps,
LAG(ActivityDate) OVER(PARTITION BY Id ORDER BY ActivityDate) prior_observed_date,
LEAD(ActivityDate) OVER(PARTITION BY Id ORDER BY ActivityDate) next_observed_date,
AVG(TotalSteps) OVER(PARTITION BY Id ORDER BY julianday(ActivityDate) RANGE BETWEEN 6 PRECEDING AND CURRENT ROW) rolling_7calendar_day_steps,
SUM(TotalSteps) OVER(PARTITION BY Id ORDER BY ActivityDate ROWS UNBOUNDED PRECEDING) running_steps
FROM clean_daily_activity;

-- QUERY: multimodal_daily
-- Purpose: Aggregate weight to day before joining
-- Business question: What can be compared on the same day?
-- Expected output: One row per retained activity day
WITH w AS (SELECT Id,weight_date,AVG(WeightKg) WeightKg,COUNT(*) logs FROM clean_weight GROUP BY Id,weight_date)
SELECT a.Id,a.ActivityDate,a.TotalSteps,s.TotalMinutesAsleep,w.WeightKg,w.logs FROM clean_daily_activity a
LEFT JOIN clean_sleep s ON a.Id=s.Id AND a.ActivityDate=s.sleep_date
LEFT JOIN w ON a.Id=w.Id AND a.ActivityDate=w.weight_date;

-- QUERY: correlation
-- Purpose: Compute Pearson at user level to avoid pseudoreplication
-- Business question: Are typical steps and calories associated between users?
-- Expected output: n and Pearson r
WITH x AS (SELECT mean_steps x,mean_calories y FROM user_summary WHERE mean_steps IS NOT NULL),
m AS (SELECT AVG(x) mx,AVG(y) my FROM x)
SELECT COUNT(*) n,SUM((x-mx)*(y-my))/NULLIF(SQRT(SUM((x-mx)*(x-mx))*SUM((y-my)*(y-my))),0) pearson_r FROM x CROSS JOIN m;


-- ===========================================================================
-- 7. FINAL INSIGHT QUERIES
-- ===========================================================================

-- QUERY: insight_user_segments
-- Purpose: Decision evidence: Which users need different support?
-- Business question: Which users need different support?
-- Expected output: Exported to sql_outputs/insight_user_segments.csv
SELECT rule_segment,COUNT(*) users,AVG(mean_steps) mean_steps,AVG(engagement_score) engagement FROM user_summary GROUP BY rule_segment;

-- QUERY: insight_weekday_weekend
-- Purpose: Decision evidence: Does the habit change on weekends?
-- Business question: Does the habit change on weekends?
-- Expected output: Exported to sql_outputs/insight_weekday_weekend.csv
SELECT weekend,COUNT(*) days,COUNT(DISTINCT Id) users,AVG(TotalSteps) mean_steps FROM clean_daily_activity GROUP BY weekend;

-- QUERY: insight_hourly_peaks
-- Purpose: Decision evidence: When are recorded steps highest?
-- Business question: When are recorded steps highest?
-- Expected output: Exported to sql_outputs/insight_hourly_peaks.csv
SELECT hour,COUNT(*) user_hours,AVG(StepTotal) mean_steps,RANK() OVER(ORDER BY AVG(StepTotal) DESC) peak_rank FROM hourly_activity GROUP BY hour;

-- QUERY: insight_sleep_activity
-- Purpose: Decision evidence: How does recorded sleep align with adjacent dates?
-- Business question: How does recorded sleep align with adjacent dates?
-- Expected output: Exported to sql_outputs/insight_sleep_activity.csv
SELECT s.Id,s.sleep_date,s.TotalMinutesAsleep,s.sleep_efficiency,
a.TotalSteps same_date_steps,p.TotalSteps previous_date_steps,n.TotalSteps next_date_steps
FROM clean_sleep s LEFT JOIN clean_daily_activity a ON a.Id=s.Id AND a.ActivityDate=s.sleep_date
LEFT JOIN clean_daily_activity p ON p.Id=s.Id AND p.ActivityDate=date(s.sleep_date,'-1 day')
LEFT JOIN clean_daily_activity n ON n.Id=s.Id AND n.ActivityDate=date(s.sleep_date,'+1 day');

-- QUERY: insight_calories_intensity
-- Purpose: Decision evidence: Are more active days associated with more total calories?
-- Business question: Are more active days associated with more total calories?
-- Expected output: Exported to sql_outputs/insight_calories_intensity.csv
SELECT steps_category,COUNT(*) days,AVG(Calories) total_daily_calories,AVG(active_minutes) active_minutes,AVG(VeryActiveMinutes) vigorous_minutes FROM clean_daily_activity GROUP BY steps_category;

-- QUERY: insight_engagement
-- Purpose: Decision evidence: Who records consistently?
-- Business question: Who records consistently?
-- Expected output: Exported to sql_outputs/insight_engagement.csv
SELECT * FROM user_summary ORDER BY engagement_score DESC;

-- QUERY: insight_weekly_retention
-- Purpose: Decision evidence: How many original users remain observable each study week?
-- Business question: How many original users remain observable each study week?
-- Expected output: Exported to sql_outputs/insight_weekly_retention.csv
SELECT CAST((julianday(ActivityDate)-julianday('2016-04-12'))/7 AS INTEGER)+1 study_week,COUNT(DISTINCT Id) observable_users,COUNT(*) valid_days FROM clean_daily_activity GROUP BY study_week;

-- QUERY: insight_who_guideline
-- Purpose: Decision evidence: Which fully observed weeks meet a WHO-inspired proxy?
-- Business question: Which fully observed weeks meet a WHO-inspired proxy?
-- Expected output: Exported to sql_outputs/insight_who_guideline.csv
SELECT study_week,COUNT(*) observed_user_weeks,SUM(valid_days=7) eligible_weeks,SUM(who_proxy=1) meeting_proxy,SUM(moderate_only_flag=1) moderate_only_meeting FROM weekly_activity GROUP BY study_week;

-- QUERY: insight_heart_rate_zones
-- Purpose: Decision evidence: What are the descriptive HR time bands?
-- Business question: What are the descriptive HR time bands?
-- Expected output: Exported to sql_outputs/insight_heart_rate_zones.csv
SELECT bpm_band,SUM(observed_seconds)/3600.0 observed_hours,SUM(samples) readings,SUM(long_gaps) excluded_gaps FROM hr_bands GROUP BY bpm_band;

-- QUERY: insight_weight_behavior
-- Purpose: Decision evidence: Is weight a broadly used feature?
-- Business question: Is weight a broadly used feature?
-- Expected output: Exported to sql_outputs/insight_weight_behavior.csv
SELECT Id,COUNT(*) logs,COUNT(DISTINCT weight_date) days,SUM(IsManualReport) manual_logs,SUM(Fat IS NULL) missing_fat,AVG(BMI) mean_recorded_bmi FROM clean_weight GROUP BY Id;

-- QUERY: reconciliation
-- Purpose: Match independently cleaned Python outputs
-- Business question: Are the two analytical paths consistent?
-- Expected output: One row of parity metrics
SELECT (SELECT COUNT(DISTINCT Id) FROM dailyActivity) activity_users,
(SELECT COUNT(*) FROM clean_daily_activity) clean_activity_rows,
(SELECT AVG(TotalSteps) FROM clean_daily_activity) average_steps,
(SELECT COUNT(*) FROM clean_sleep) clean_sleep_rows,
(SELECT AVG(TotalMinutesAsleep) FROM clean_sleep) average_sleep_minutes,
(SELECT COUNT(*) FROM clean_weight) clean_weight_rows;

-- QUERY: hr_sampling_audit
-- Purpose: Verify irregular sampling and suspicious heart rates.
-- Business question: Can readings be treated as fixed 15-second intervals?
-- Expected output: Interval frequency, including gaps; seconds rounded to integer.
WITH intervals AS (
 SELECT ROUND((julianday(LEAD(Time) OVER(PARTITION BY Id ORDER BY Time))-julianday(Time))*86400) seconds
 FROM heartrate_seconds)
SELECT seconds,COUNT(*) intervals FROM intervals WHERE seconds IS NOT NULL GROUP BY seconds ORDER BY intervals DESC;

-- QUERY: hr_value_audit
-- Purpose: Quantify physiological plausibility without diagnosing users.
-- Business question: How many observations are excluded from HR summaries?
-- Expected output: Reading counts, raw extrema, rejected readings.
SELECT COUNT(*) readings,MIN(Value) min_bpm,MAX(Value) max_bpm,
 SUM(Value<30 OR Value>220) out_of_bounds FROM heartrate_seconds;

-- QUERY: minute_code_audit
-- Purpose: Preserve undocumented sleep code labels.
-- Business question: Can state codes alone establish sleep-onset latency?
-- Expected output: Raw sleep code frequencies; no clinical interpretation.
SELECT value raw_code,COUNT(*) rows FROM minuteSleep GROUP BY value;
