-- CT-07 Round-thousand amounts
-- Risk indicator: invoices for exact round thousands (>= $5,000) are less common in genuine
-- trade and are a standard fraud-analytics flag. A flag needs follow-up, not a conclusion.
SELECT
    payment_id,
    'Round amount ' || printf('%.2f', amount) AS detail
FROM payments
WHERE amount >= 5000
  AND ROUND(amount, 2) = ROUND(amount, 0)
  AND CAST(ROUND(amount, 0) AS INTEGER) % 1000 = 0;
