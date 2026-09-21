-- Weekly 7-day player retention rate by segment and region, aggregated from
-- fct_player_sessions. Not materialized as a queryable dataset in the
-- agentic-data-analyst reference deployment: see target/README.md.
select
    segment,
    region,
    date_trunc('week', signup_at) as cohort_week,
    avg(case when retained_7d then 1.0 else 0.0 end) as retention_7d,
    count(distinct player_id) as player_count
from {{ ref('fct_player_sessions') }}
group by 1, 2, 3
