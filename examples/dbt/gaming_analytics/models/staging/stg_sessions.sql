-- Cleaned player session staging model built directly from the raw session
-- source.
select
    session_id,
    player_id,
    session_start,
    session_end,
    duration_minutes,
    device
from {{ source('raw', 'raw_sessions') }}
