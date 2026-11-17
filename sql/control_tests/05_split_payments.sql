-- CT-05 Split payments
-- Control objective: a purchase is not broken into smaller payments to stay under an approval limit.
-- Exception: two or more payments to the same vendor, on the same day, approved by the same person,
--            each within that person's limit but together above it.
WITH groups AS (
    SELECT
        p.vendor_id,
        date(p.posted_at) AS pay_date,
        p.approved_by,
        e.approval_limit,
        COUNT(*)      AS n_payments,
        SUM(p.amount) AS total_amount,
        MAX(p.amount) AS max_amount
    FROM payments p
    JOIN employees e ON e.employee_id = p.approved_by
    GROUP BY p.vendor_id, date(p.posted_at), p.approved_by
    HAVING COUNT(*) >= 2
       AND SUM(p.amount) > e.approval_limit
       AND MAX(p.amount) <= e.approval_limit
)
SELECT
    p.payment_id,
    g.n_payments || ' payments to ' || g.vendor_id || ' on ' || g.pay_date
        || ' total ' || printf('%.2f', g.total_amount)
        || ' vs limit ' || printf('%,d', g.approval_limit) AS detail
FROM payments p
JOIN groups g
  ON g.vendor_id = p.vendor_id
 AND g.pay_date = date(p.posted_at)
 AND g.approved_by = p.approved_by;
