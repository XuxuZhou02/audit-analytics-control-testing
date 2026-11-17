-- CT-09 Vendor master integrity
-- Control objective: payments go only to vendors that exist in the vendor master and are active.
-- Exception: vendor_id not in the master, or paid after the vendor was deactivated.
SELECT
    p.payment_id,
    CASE WHEN v.vendor_id IS NULL THEN 'Vendor ' || p.vendor_id || ' not in vendor master'
         ELSE 'Vendor ' || p.vendor_id || ' inactive since ' || v.inactive_date END AS detail
FROM payments p
LEFT JOIN vendors v ON v.vendor_id = p.vendor_id
WHERE v.vendor_id IS NULL
   OR (v.status = 'Inactive' AND date(p.posted_at) > v.inactive_date);
