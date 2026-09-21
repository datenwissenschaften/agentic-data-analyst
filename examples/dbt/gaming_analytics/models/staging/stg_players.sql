-- Cleaned, one-row-per-player staging model built directly from the raw
-- player source. Curated entry point other models join against for player
-- attributes.
select
    player_id,
    signup_at,
    segment,
    region,
    acquisition_channel
from {{ source('raw', 'raw_players') }}
