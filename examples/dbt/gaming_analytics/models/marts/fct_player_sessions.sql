-- One row per player session, joined to player attributes and event
-- volume, with a derived 7-day-retained flag consumed by
-- mart_player_retention. Not materialized as a queryable dataset in the
-- agentic-data-analyst reference deployment: see target/README.md.
with events as (
    select session_id, count(*) as event_count
    from {{ source('raw', 'raw_events') }}
    group by session_id
)

select
    s.session_id,
    s.player_id,
    p.segment,
    p.region,
    s.session_start,
    p.signup_at,
    datediff('day', p.signup_at, s.session_start) >= 7 as retained_7d,
    coalesce(events.event_count, 0) as event_count
from {{ ref('stg_sessions') }} as s
inner join {{ ref('stg_players') }} as p on p.player_id = s.player_id
left join events on events.session_id = s.session_id
