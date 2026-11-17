"""Known-answer tests: every planted issue must be found, and key controls must not over-flag."""

import pandas as pd
import pytest

from audit_analytics.analytics import completeness_checks, run_all_tests, vendor_outliers
from audit_analytics.controls import CONTROL_TESTS
from audit_analytics.generate_ledger import PLANTED, generate


@pytest.fixture(scope="module")
def ledger():
    return generate(seed=2027)


@pytest.fixture(scope="module")
def exceptions(ledger):
    tables = {"payments": ledger.payments, "vendors": ledger.vendors, "employees": ledger.employees}
    return run_all_tests(tables)


def _expected(ledger, test):
    return set(ledger.planted.loc[ledger.planted.issue_type.isin(test.planted_issue.split("|")), "payment_id"])


def test_generator_plants_requested_counts(ledger):
    counts = ledger.planted.issue_type.value_counts()
    for issue, n in PLANTED.items():
        if issue == "SPLIT":
            assert ledger.planted.loc[ledger.planted.issue_type == "SPLIT", "group_id"].nunique() == n
        else:
            assert counts[issue] == n, issue


def test_generator_is_reproducible():
    a, b = generate(seed=7), generate(seed=7)
    pd.testing.assert_frame_equal(a.payments, b.payments)


def test_population_is_complete(ledger):
    checks = completeness_checks(
        {"payments": ledger.payments, "vendors": ledger.vendors, "employees": ledger.employees}
    ).set_index("check").result
    assert checks["Duplicate payment_id"] == "0"
    assert checks["Missing values in required fields"] == "0"
    assert checks["Non-positive amounts"] == "0"


@pytest.mark.parametrize("test", [t for t in CONTROL_TESTS if t.sql_file], ids=lambda t: t.test_id)
def test_sql_tests_find_exactly_the_planted_issues(ledger, exceptions, test):
    got = set(exceptions.loc[exceptions.test_id == test.test_id, "payment_id"])
    assert got == _expected(ledger, test)


def test_outlier_test_finds_all_planted_outliers(ledger, exceptions):
    test = next(t for t in CONTROL_TESTS if t.test_id == "CT-10")
    got = set(exceptions.loc[exceptions.test_id == "CT-10", "payment_id"])
    assert _expected(ledger, test) <= got


def test_outlier_false_positive_rate_on_clean_records_is_low(ledger, exceptions):
    got = set(exceptions.loc[exceptions.test_id == "CT-10", "payment_id"])
    clean = set(ledger.payments.payment_id) - set(ledger.planted.payment_id)
    assert len(got & clean) / len(clean) < 0.005


def test_every_exception_traces_to_a_payment(ledger, exceptions):
    assert exceptions.payment_id.isin(ledger.payments.payment_id).all()
    assert exceptions.detail.notna().all()


# --- edge cases on hand-built data -------------------------------------------------

def _tables(payments):
    employees = pd.DataFrame({
        "employee_id": ["E1", "E2"], "employee_name": ["a", "b"], "role": ["AP Clerk", "AP Supervisor"],
        "can_create": [True, True], "approval_limit": [0, 50_000],
    })
    vendors = pd.DataFrame({
        "vendor_id": ["V1"], "vendor_name": ["v"], "created_date": ["2020-01-01"],
        "status": ["Active"], "inactive_date": [None],
    })
    base = {"invoice_date": "2025-01-01", "currency": "CAD", "payment_method": "EFT"}
    return {"payments": pd.DataFrame([{**base, **p} for p in payments]), "vendors": vendors, "employees": employees}


def _ids(tables, test_id):
    exc = run_all_tests(tables)
    return set(exc.loc[exc.test_id == test_id, "payment_id"])


def test_duplicate_flags_only_the_later_payment():
    t = _tables([
        dict(payment_id="P1", vendor_id="V1", invoice_no="I1", amount=1234.56, created_by="E1", approved_by="E2", posted_at="2025-03-03 10:00:00"),
        dict(payment_id="P2", vendor_id="V1", invoice_no="I2", amount=1234.56, created_by="E1", approved_by="E2", posted_at="2025-03-20 10:00:00"),
        dict(payment_id="P3", vendor_id="V1", invoice_no="I3", amount=1234.56, created_by="E1", approved_by="E2", posted_at="2025-06-20 10:00:00"),
    ])
    # P2 is within 30 days of P1; P3 is 90 days after P2 with a different invoice, so not a duplicate
    assert _ids(t, "CT-01") == {"P2"}


def test_limit_boundaries():
    t = _tables([
        dict(payment_id="AT", vendor_id="V1", invoice_no="I1", amount=50_000.00, created_by="E1", approved_by="E2", posted_at="2025-03-03 10:00:00"),
        dict(payment_id="OVER", vendor_id="V1", invoice_no="I2", amount=50_000.01, created_by="E1", approved_by="E2", posted_at="2025-03-04 10:00:00"),
        dict(payment_id="LOW", vendor_id="V1", invoice_no="I3", amount=47_499.99, created_by="E1", approved_by="E2", posted_at="2025-03-05 10:00:00"),
    ])
    assert _ids(t, "CT-03") == {"OVER"}  # at the limit is allowed
    assert _ids(t, "CT-04") == {"AT"}  # 95% boundary is 47,500.00


def test_off_hours_boundaries():
    t = _tables([
        dict(payment_id="H0559", vendor_id="V1", invoice_no="I1", amount=100.01, created_by="E1", approved_by="E2", posted_at="2025-03-04 05:59:00"),
        dict(payment_id="H0600", vendor_id="V1", invoice_no="I2", amount=100.02, created_by="E1", approved_by="E2", posted_at="2025-03-04 06:00:00"),
        dict(payment_id="H2000", vendor_id="V1", invoice_no="I3", amount=100.03, created_by="E1", approved_by="E2", posted_at="2025-03-05 20:00:00"),
        dict(payment_id="SAT", vendor_id="V1", invoice_no="I4", amount=100.04, created_by="E1", approved_by="E2", posted_at="2025-03-08 12:00:00"),
    ])
    assert _ids(t, "CT-06") == {"H0559", "H2000", "SAT"}


def test_unknown_vendor_and_round_amount():
    t = _tables([
        dict(payment_id="UNK", vendor_id="V404", invoice_no="I1", amount=4999.00, created_by="E1", approved_by="E2", posted_at="2025-03-04 10:00:00"),
        dict(payment_id="R5K", vendor_id="V1", invoice_no="I2", amount=5000.00, created_by="E1", approved_by="E2", posted_at="2025-03-05 10:00:00"),
        dict(payment_id="R5K01", vendor_id="V1", invoice_no="I3", amount=5000.01, created_by="E1", approved_by="E2", posted_at="2025-03-06 10:00:00"),
    ])
    assert _ids(t, "CT-09") == {"UNK"}
    assert _ids(t, "CT-07") == {"R5K"}


def test_vendor_outliers_needs_minimum_history():
    rows = [dict(payment_id=f"P{i}", vendor_id="V1", amount=1000 + i) for i in range(10)]
    rows.append(dict(payment_id="BIG", vendor_id="V1", amount=1_000_000))
    assert vendor_outliers(pd.DataFrame(rows)).empty  # fewer than 20 payments: not tested
