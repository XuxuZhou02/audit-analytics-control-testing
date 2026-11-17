"""Load the ledger into SQLite, run the SQL control tests, and run the statistical tests."""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd
from scipy import stats

from . import PROJECT_ROOT
from .controls import CONTROL_TESTS, ControlTest

SQL_DIR = PROJECT_ROOT / "sql" / "control_tests"

# ---------------------------------------------------------------------------
# Loading
# ---------------------------------------------------------------------------


def load_tables(data_dir: Path) -> dict[str, pd.DataFrame]:
    return {
        "payments": pd.read_csv(data_dir / "payments.csv", dtype={"invoice_no": str}),
        "vendors": pd.read_csv(data_dir / "vendors.csv"),
        "employees": pd.read_csv(data_dir / "employees.csv"),
    }


def completeness_checks(tables: dict[str, pd.DataFrame]) -> pd.DataFrame:
    """Basic population checks an auditor records before testing (record counts, totals, keys)."""
    p = tables["payments"]
    rows = [
        ("Payment records", f"{len(p):,}"),
        ("Total amount (CAD)", f"{p.amount.sum():,.2f}"),
        ("Posting period", f"{p.posted_at.min()[:10]} to {p.posted_at.max()[:10]}"),
        ("Duplicate payment_id", str(int(p.payment_id.duplicated().sum()))),
        ("Missing values in required fields",
         str(int(p[["payment_id", "vendor_id", "amount", "created_by", "approved_by", "posted_at"]].isna().sum().sum()))),
        ("Non-positive amounts", str(int((p.amount <= 0).sum()))),
        ("Vendors in master", f"{len(tables['vendors']):,}"),
        ("Employees in master", f"{len(tables['employees']):,}"),
    ]
    return pd.DataFrame(rows, columns=["check", "result"])


def to_sqlite(tables: dict[str, pd.DataFrame]) -> sqlite3.Connection:
    con = sqlite3.connect(":memory:")
    for name, df in tables.items():
        df.to_sql(name, con, index=False)
    con.execute("CREATE INDEX ix_pay_vendor ON payments(vendor_id)")
    return con


# ---------------------------------------------------------------------------
# Control tests
# ---------------------------------------------------------------------------


def run_sql_test(con: sqlite3.Connection, test: ControlTest) -> pd.DataFrame:
    sql = (SQL_DIR / test.sql_file).read_text()
    return pd.read_sql_query(sql, con)


def vendor_outliers(payments: pd.DataFrame, min_payments: int = 20, threshold: float = 3.5) -> pd.DataFrame:
    """Robust z-score on log(amount) within each vendor (Iglewicz & Hoaglin modified z-score)."""
    df = payments[["payment_id", "vendor_id", "amount"]].copy()
    df["log_amt"] = np.log(df.amount)
    g = df.groupby("vendor_id").log_amt
    df["n"] = g.transform("size")
    df["median"] = g.transform("median")
    df["mad"] = g.transform(lambda s: np.median(np.abs(s - np.median(s))))
    df = df[(df.n >= min_payments) & (df.mad > 0)]
    df["robust_z"] = 0.6745 * (df.log_amt - df["median"]) / df.mad
    out = df[df.robust_z.abs() > threshold].copy()
    out["detail"] = [
        f"Robust z = {z:.2f}; vendor median {np.exp(m):,.2f}, paid {a:,.2f}"
        for z, m, a in zip(out.robust_z, out["median"], out.amount)
    ]
    return out[["payment_id", "detail"]].reset_index(drop=True)


def run_all_tests(tables: dict[str, pd.DataFrame]) -> pd.DataFrame:
    """Return one row per exception: test_id, payment_id, detail."""
    con = to_sqlite(tables)
    frames = []
    for test in CONTROL_TESTS:
        if test.sql_file:
            res = run_sql_test(con, test)
        elif test.test_id == "CT-10":
            res = vendor_outliers(tables["payments"])
        else:  # pragma: no cover
            raise ValueError(test.test_id)
        res.insert(0, "test_id", test.test_id)
        frames.append(res)
    con.close()
    exc = pd.concat(frames, ignore_index=True)
    pay = tables["payments"].set_index("payment_id")
    exc = exc.join(pay[["vendor_id", "amount", "created_by", "approved_by", "posted_at"]], on="payment_id")
    return exc


# ---------------------------------------------------------------------------
# Benford's Law
# ---------------------------------------------------------------------------

# Nigrini's mean-absolute-deviation conformity ranges for first digits.
NIGRINI_FIRST_DIGIT = [(0.006, "Close conformity"), (0.012, "Acceptable conformity"),
                       (0.015, "Marginally acceptable conformity"), (np.inf, "Nonconformity")]


@dataclass
class BenfordResult:
    table: pd.DataFrame
    n: int
    chi2: float
    p_value: float
    mad: float
    conclusion: str


def first_digit(amounts: pd.Series) -> pd.Series:
    a = amounts[amounts >= 10].abs()
    return (a / 10 ** np.floor(np.log10(a))).astype(int)


def benford(amounts: pd.Series) -> BenfordResult:
    d = first_digit(amounts)
    n = len(d)
    digits = np.arange(1, 10)
    expected_p = np.log10(1 + 1 / digits)
    observed = d.value_counts().reindex(digits, fill_value=0).to_numpy()
    observed_p = observed / n
    chi2, p = stats.chisquare(observed, expected_p * n)
    mad = float(np.mean(np.abs(observed_p - expected_p)))
    # Nigrini z-statistic per digit (with continuity correction)
    z = (np.abs(observed_p - expected_p) - 1 / (2 * n)) / np.sqrt(expected_p * (1 - expected_p) / n)
    table = pd.DataFrame({
        "digit": digits, "observed": observed, "observed_pct": observed_p,
        "expected_pct": expected_p, "z_stat": np.clip(z, 0, None),
    })
    conclusion = next(label for limit, label in NIGRINI_FIRST_DIGIT if mad <= limit)
    return BenfordResult(table, n, float(chi2), float(p), mad, conclusion)
