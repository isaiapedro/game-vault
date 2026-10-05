-- Separate explicit trailing PlayStation system labels from catalog titles.
-- Examples: "Example - PS3", "Example | PS3", "Example (PS3)".
WITH normalized AS (
    SELECT id,
        regexp_replace(
            title,
            '[[:space:]]*([|/·:-][[:space:]]*)?(\(PS(3|4|5|[[:space:]]*VITA)\)|\[PS(3|4|5|[[:space:]]*VITA)\]|PS(3|4|5|[[:space:]]*VITA))[[:space:]]*$',
            '', 'i'
        ) AS clean_title,
        CASE
            WHEN title ~* '(\(PS3\)|\[PS3\]|PS3)[[:space:]]*$' THEN 'PS3'
            WHEN title ~* '(\(PS4\)|\[PS4\]|PS4)[[:space:]]*$' THEN 'PS4'
            WHEN title ~* '(\(PS5\)|\[PS5\]|PS5)[[:space:]]*$' THEN 'PS5'
            WHEN title ~* '(\(PS[[:space:]]*VITA\)|\[PS[[:space:]]*VITA\]|PS[[:space:]]*VITA)[[:space:]]*$' THEN 'PSVITA'
        END AS parsed_platform
    FROM games
    WHERE title ~* '([[:space:]]+|[|/·:-][[:space:]]*)(\(PS(3|4|5|[[:space:]]*VITA)\)|\[PS(3|4|5|[[:space:]]*VITA)\]|PS(3|4|5|[[:space:]]*VITA))[[:space:]]*$'
)
UPDATE games g
SET title = btrim(n.clean_title), platform = n.parsed_platform
FROM normalized n
WHERE g.id = n.id AND btrim(n.clean_title) <> '' AND n.parsed_platform IS NOT NULL;
