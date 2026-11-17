-- CT-04 Amounts just below the approval limit
-- Risk indicator: amounts set just under a limit can signal threshold avoidance.
-- Exception: amount between 95% and 100% of the approver's limit.
SELECT
    p.payment_id,
    'Amount is ' || printf('%.1f', 100.0 * p.amount / e.approval_limit) || '% of '
        || p.approved_by || '''s limit ' || printf('%,d', e.approval_limit) AS detail
FROM payments p
JOIN employees e ON e.employee_id = p.approved_by
WHERE e.approval_limit > 0
  AND p.amount >= 0.95 * e.approval_limit
  AND p.amount <= e.approval_limit;
