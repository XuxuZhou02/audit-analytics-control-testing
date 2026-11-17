"""Catalogue of control tests: what each test checks, why it matters, and how it is rated.

The wording here feeds the generated workpapers and the findings memo. Ratings use a
simple High / Medium / Low scale based on the nature of the control, not on the number
of exceptions, because one exception in a key control can matter more than many flags
on a risk indicator.
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class ControlTest:
    test_id: str
    name: str
    kind: str  # "Control" = an exception is a control failure; "Indicator" = needs follow-up
    sql_file: str | None
    planted_issue: str | None  # issue type in planted_issues.csv that this test should find
    objective: str
    risk: str
    procedure: str
    rating: str
    follow_up: str
    management_action: str


CONTROL_TESTS: list[ControlTest] = [
    ControlTest(
        "CT-01", "Duplicate payments", "Control", "01_duplicate_payments.sql", "DUPLICATE",
        objective="Each vendor invoice is paid only once.",
        risk="Cash leaves the bank twice for one obligation; recovery depends on the vendor's cooperation.",
        procedure="For every vendor and amount, compare each payment with the previous one (window function). "
                  "Flag the later payment when the invoice number matches or the two are within 30 days.",
        rating="High",
        follow_up="Confirm with the vendor statement whether the second payment was a genuine second invoice; "
                  "request a refund or credit note where it was not.",
        management_action="Add a hard stop in the payment system on vendor + invoice number + amount, "
                          "and run this query before each payment run.",
    ),
    ControlTest(
        "CT-02", "Segregation of duties", "Control", "02_segregation_of_duties.sql", "SOD",
        objective="The person who creates a payment cannot also approve it.",
        risk="One person can create and release an unauthorised payment without a second check.",
        procedure="Flag every payment where created_by equals approved_by.",
        rating="High",
        follow_up="Obtain support for each payment and confirm it was for a genuine invoice; check whether "
                  "the system allowed self-approval or a role was misconfigured.",
        management_action="Configure the workflow to block self-approval and review AP Supervisor role access quarterly.",
    ),
    ControlTest(
        "CT-03", "Approval above delegated authority", "Control", "03_exceeds_approval_authority.sql", "EXCEEDS_LIMIT",
        objective="Payments are approved by someone whose delegated limit covers the amount.",
        risk="Large payments bypass the level of review the delegation of authority requires.",
        procedure="Join each payment to the approver's limit in the employee table and flag amounts above it.",
        rating="High",
        follow_up="Check whether a higher-level approval was obtained outside the system (e.g. by email) and "
                  "whether the limit table is current.",
        management_action="Enforce limits in the workflow so payments above an approver's limit route to the next level.",
    ),
    ControlTest(
        "CT-04", "Amounts just below approval limit", "Indicator", "04_just_below_approval_limit.sql", "JUST_BELOW_LIMIT",
        objective="Payment amounts are not set to avoid a higher level of approval.",
        risk="Amounts set just under a limit can indicate deliberate threshold avoidance.",
        procedure="Flag payments between 95% and 100% of the approver's limit.",
        rating="Medium",
        follow_up="Compare each flagged amount with the underlying invoice and purchase order; look for a "
                  "pattern by creator, approver or vendor.",
        management_action="Include near-limit payments in the monthly management review sample.",
    ),
    ControlTest(
        "CT-05", "Split payments", "Control", "05_split_payments.sql", "SPLIT",
        objective="Purchases are not split into smaller payments to stay under an approval limit.",
        risk="Splitting defeats the delegation of authority while each payment looks compliant.",
        procedure="Group payments by vendor, day and approver; flag groups of two or more where each payment "
                  "is within the limit but the total is above it.",
        rating="High",
        follow_up="Obtain the invoices in each group and confirm whether they relate to one purchase.",
        management_action="Add a same-vendor, same-day aggregation check to the approval workflow.",
    ),
    ControlTest(
        "CT-06", "Off-hours posting", "Indicator", "06_off_hours_posting.sql", "OFF_HOURS",
        objective="Payments are processed during normal, supervised business hours.",
        risk="Payments posted at weekends or late at night are less likely to be reviewed as they happen.",
        procedure="Flag payments posted on Saturday or Sunday, or between 20:00 and 05:59.",
        rating="Medium",
        follow_up="Check system access logs and whether the work was scheduled (e.g. month-end) and approved.",
        management_action="Restrict payment release outside business hours to named users with documented approval.",
    ),
    ControlTest(
        "CT-07", "Round-thousand amounts", "Indicator", "07_round_amounts.sql", "ROUND_AMOUNT",
        objective="Payment amounts reflect real invoices rather than estimates or fabricated values.",
        risk="Exact round amounts are a common feature of fictitious or estimated invoices.",
        procedure="Flag amounts of $5,000 or more that are exact multiples of $1,000.",
        rating="Low",
        follow_up="Vouch each flagged payment to its invoice and goods-received evidence.",
        management_action="No process change needed unless follow-up finds unsupported invoices.",
    ),
    ControlTest(
        "CT-08", "Large payment to new vendor", "Indicator", "08_new_vendor_large_payment.sql", "NEW_VENDOR_LARGE",
        objective="New vendors are validated before large amounts are paid to them.",
        risk="Fictitious vendors are often set up shortly before a large payment.",
        procedure="Flag payments over $50,000 made within 30 days of the vendor's creation date.",
        rating="Medium",
        follow_up="Check the vendor onboarding file: who created the vendor, bank-account verification, "
                  "and whether the creator also handled the payment.",
        management_action="Require independent bank-account verification before a new vendor's first payment over $50,000.",
    ),
    ControlTest(
        "CT-09", "Vendor master integrity", "Control", "09_vendor_master_integrity.sql", "INACTIVE_VENDOR|UNKNOWN_VENDOR",
        objective="Payments go only to vendors that exist in the vendor master and are active.",
        risk="Payments to unknown or deactivated vendors bypass vendor due diligence.",
        procedure="Left-join payments to the vendor master; flag missing vendors and payments dated after deactivation.",
        rating="High",
        follow_up="Trace each payment's bank details and identify how the system accepted the vendor ID.",
        management_action="Add a referential-integrity check so payments cannot be released to missing or inactive vendors.",
    ),
    ControlTest(
        "CT-10", "Statistical outliers by vendor", "Indicator", None, "OUTLIER",
        objective="Payment amounts are consistent with each vendor's usual invoice size.",
        risk="An unusually large payment can signal an error, inflated invoice or a misused vendor account.",
        procedure="For vendors with at least 20 payments, compute a robust z-score on log(amount) using the "
                  "median and MAD; flag scores above 3.5. Implemented in Python (src/audit_analytics/analytics.py).",
        rating="Medium",
        follow_up="Vouch the flagged payments to invoices and confirm the business reason for the size.",
        management_action="Add vendor-level outlier review to the monthly AP analytics pack.",
    ),
]

BY_ID = {t.test_id: t for t in CONTROL_TESTS}
