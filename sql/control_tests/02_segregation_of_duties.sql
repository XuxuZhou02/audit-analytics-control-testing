-- CT-02 Segregation of duties
-- Control objective: the person who creates a payment cannot also approve it.
-- Exception: created_by = approved_by.
SELECT
    p.payment_id,
    'Created and approved by ' || p.created_by || ' (' || e.role || ')' AS detail
FROM payments p
LEFT JOIN employees e ON e.employee_id = p.created_by
WHERE p.created_by = p.approved_by;
