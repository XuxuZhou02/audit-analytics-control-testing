-- CT-01 Duplicate payments
-- Control objective: each vendor invoice is paid only once.
-- Exception: a payment to the same vendor for the same amount as an earlier payment,
--            where the invoice number matches or the earlier payment was within 30 days.
-- Only the later payment of each pair is flagged (the earlier one is the original).
WITH ordered AS (
    SELECT
        payment_id, vendor_id, invoice_no, amount, posted_at,
        LAG(payment_id) OVER w AS prev_payment_id,
        LAG(invoice_no) OVER w AS prev_invoice_no,
        LAG(posted_at)  OVER w AS prev_posted_at
    FROM payments
    WINDOW w AS (PARTITION BY vendor_id, amount ORDER BY posted_at, payment_id)
)
SELECT
    payment_id,
    'Same vendor and amount as ' || prev_payment_id
        || CASE WHEN invoice_no = prev_invoice_no THEN ', same invoice ' || invoice_no
                ELSE ', different invoice' END
        || ', ' || CAST(ROUND(julianday(posted_at) - julianday(prev_posted_at), 1) AS TEXT)
        || ' days later' AS detail
FROM ordered
WHERE prev_payment_id IS NOT NULL
  AND (invoice_no = prev_invoice_no
       OR julianday(posted_at) - julianday(prev_posted_at) <= 30);
