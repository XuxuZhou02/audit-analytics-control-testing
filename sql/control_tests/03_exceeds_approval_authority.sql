-- CT-03 Approval above delegated authority
-- Control objective: payments are approved only by someone whose approval limit covers the amount.
-- Exception: amount > approver's approval_limit, or the approver has no approval authority.
SELECT
    p.payment_id,
    'Amount ' || printf('%.2f', p.amount) || ' > limit ' || printf('%,d', COALESCE(e.approval_limit, 0))
        || ' of ' || p.approved_by AS detail
FROM payments p
LEFT JOIN employees e ON e.employee_id = p.approved_by
WHERE p.amount > COALESCE(e.approval_limit, 0);
