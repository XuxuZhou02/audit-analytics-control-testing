-- CT-06 Off-hours posting
-- Risk indicator: payments posted on weekends or between 20:00 and 05:59 fall outside
-- normal supervised processing.
SELECT
    payment_id,
    'Posted ' || posted_at || ' ('
        || CASE strftime('%w', posted_at) WHEN '0' THEN 'Sunday' WHEN '6' THEN 'Saturday'
                ELSE 'weekday, ' || strftime('%H:%M', posted_at) END || ')' AS detail
FROM payments
WHERE strftime('%w', posted_at) IN ('0', '6')
   OR CAST(strftime('%H', posted_at) AS INTEGER) < 6
   OR CAST(strftime('%H', posted_at) AS INTEGER) >= 20;
