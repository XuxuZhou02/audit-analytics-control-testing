-- CT-08 Large payment to a new vendor
-- Risk indicator: a payment over $50,000 within 30 days of the vendor being created.
SELECT
    p.payment_id,
    'Vendor ' || p.vendor_id || ' created ' || v.created_date || ', paid '
        || printf('%.2f', p.amount) || ' after '
        || CAST(CAST(julianday(date(p.posted_at)) - julianday(v.created_date) AS INTEGER) AS TEXT)
        || ' days' AS detail
FROM payments p
JOIN vendors v ON v.vendor_id = p.vendor_id
WHERE p.amount > 50000
  AND julianday(date(p.posted_at)) - julianday(v.created_date) BETWEEN 0 AND 30;
