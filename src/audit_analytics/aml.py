"""Transaction-monitoring rules evaluated against labelled synthetic AML data.

Data: IBM "Transactions for Anti Money Laundering (AML)" on Kaggle (synthetic, with an
``Is Laundering`` label). Download ``HI-Small_Trans.csv`` and place it in ``data/raw/``.
The file is not committed to this repository.

The rules are simplified versions of common monitoring scenarios. They are not any
bank's actual rules, and the thresholds are illustrative.

Usage:
    python -m audit_analytics.aml --file data/raw/HI-Small_Trans.csv
"""

from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np
import pandas as pd

from . import PROJECT_ROOT

STRUCTURING_LOW, STRUCTURING_HIGH, STRUCTURING_MIN_COUNT = 8_000, 10_000, 3
FAN_MIN_COUNTERPARTIES = 5
PASS_THROUGH_WINDOW = pd.Timedelta(hours=24)
PASS_THROUGH_TOLERANCE = 0.10
LARGE_CASH_THRESHOLD = 10_000

RULES = {
    "R1": ("Structuring", f"3+ payments from one account, each {STRUCTURING_LOW:,}-{STRUCTURING_HIGH - 1:,} "
                          "in the same currency, within 24 hours (rolling)"),
    "R2": ("Fan-out", f"Account pays {FAN_MIN_COUNTERPARTIES}+ distinct counterparties on the same day"),
    "R3": ("Fan-in", f"Account receives from {FAN_MIN_COUNTERPARTIES}+ distinct counterparties on the same day"),
    "R4": ("Rapid pass-through", "Account sends out within 24 hours an amount within 10% of an amount it "
                                 "just received, in the same currency"),
    "R5": ("Large cash", f"Cash payment of {LARGE_CASH_THRESHOLD:,} or more (currency-agnostic illustration "
                         "of a large-cash reporting threshold)"),
}

IBM_COLUMNS = ["Timestamp", "From Bank", "Account", "To Bank", "Account.1", "Amount Received",
               "Receiving Currency", "Amount Paid", "Payment Currency", "Payment Format", "Is Laundering"]


def load_ibm(path: Path, nrows: int | None = None) -> pd.DataFrame:
    df = pd.read_csv(path, nrows=nrows, dtype={"From Bank": str, "To Bank": str, "Account": str, "Account.1": str})
    missing = [c for c in IBM_COLUMNS if c not in df.columns]
    if missing:
        raise ValueError(f"Unexpected file layout, missing columns: {missing}")
    out = pd.DataFrame({
        "ts": pd.to_datetime(df["Timestamp"], format="%Y/%m/%d %H:%M"),
        "from_acct": df["From Bank"] + "|" + df["Account"],
        "to_acct": df["To Bank"] + "|" + df["Account.1"],
        "amount": df["Amount Paid"].astype(float),
        "currency": df["Payment Currency"],
        "amount_received": df["Amount Received"].astype(float),
        "currency_received": df["Receiving Currency"],
        "format": df["Payment Format"],
        "label": df["Is Laundering"].astype(int),
    })
    out.index.name = "txn_id"
    return out.reset_index()


def rule_structuring(tx: pd.DataFrame) -> pd.Series:
    band = tx[(tx.amount >= STRUCTURING_LOW) & (tx.amount < STRUCTURING_HIGH)].sort_values("ts")
    flagged = pd.Series(False, index=tx.index)
    if band.empty:
        return flagged
    for _, grp in band.groupby(["from_acct", "currency"], sort=False):
        if len(grp) < STRUCTURING_MIN_COUNT:
            continue
        times = grp.ts.to_numpy()
        # count of band payments within the 24h window ending at each payment
        start = np.searchsorted(times, times - np.timedelta64(24, "h"), side="left")
        counts = np.arange(len(times)) - start + 1
        hit_end = np.where(counts >= STRUCTURING_MIN_COUNT)[0]
        idx = grp.index.to_numpy()
        for e in hit_end:
            flagged.loc[idx[start[e]:e + 1]] = True
    return flagged


def _fan(tx: pd.DataFrame, side: str, other: str) -> pd.Series:
    day = tx.ts.dt.floor("D")
    n = tx.assign(day=day).groupby([side, "day"])[other].transform("nunique")
    return n >= FAN_MIN_COUNTERPARTIES


def rule_fan_out(tx: pd.DataFrame) -> pd.Series:
    return _fan(tx, "from_acct", "to_acct")


def rule_fan_in(tx: pd.DataFrame) -> pd.Series:
    return _fan(tx, "to_acct", "from_acct")


def rule_pass_through(tx: pd.DataFrame) -> pd.Series:
    """Flag outgoing payments that follow an incoming payment of similar size within 24h."""
    incoming = tx[["ts", "to_acct", "amount_received", "currency_received"]].rename(
        columns={"to_acct": "acct", "amount_received": "in_amount", "currency_received": "currency"})
    incoming = incoming[tx.from_acct != tx.to_acct].sort_values("ts")
    outgoing = tx[["txn_id", "ts", "from_acct", "amount", "currency"]].rename(columns={"from_acct": "acct"})
    outgoing = outgoing[tx.from_acct != tx.to_acct].sort_values("ts")
    merged = pd.merge_asof(outgoing, incoming, on="ts", by=["acct", "currency"],
                           tolerance=PASS_THROUGH_WINDOW, direction="backward", allow_exact_matches=False)
    hit = merged.in_amount.notna() & (
        (merged.amount - merged.in_amount).abs() <= PASS_THROUGH_TOLERANCE * merged.in_amount)
    flagged = pd.Series(False, index=tx.index)
    ids = set(merged.loc[hit, "txn_id"])
    flagged[tx.txn_id.isin(ids)] = True
    return flagged


def rule_large_cash(tx: pd.DataFrame) -> pd.Series:
    return (tx.format == "Cash") & (tx.amount >= LARGE_CASH_THRESHOLD)


RULE_FUNCS = {"R1": rule_structuring, "R2": rule_fan_out, "R3": rule_fan_in,
              "R4": rule_pass_through, "R5": rule_large_cash}


def apply_rules(tx: pd.DataFrame) -> pd.DataFrame:
    flags = pd.DataFrame({rid: f(tx).to_numpy() for rid, f in RULE_FUNCS.items()}, index=tx.index)
    flags["ANY"] = flags.any(axis=1)
    return flags


def evaluate(tx: pd.DataFrame, flags: pd.DataFrame) -> pd.DataFrame:
    y = tx.label.astype(bool).to_numpy()
    base_rate = y.mean()
    rows = []
    for rid in list(RULE_FUNCS) + ["ANY"]:
        f = flags[rid].to_numpy()
        tp = int((f & y).sum())
        fp = int((f & ~y).sum())
        flagged = int(f.sum())
        precision = tp / flagged if flagged else np.nan
        recall = tp / y.sum() if y.sum() else np.nan
        rows.append({
            "rule": rid,
            "name": RULES[rid][0] if rid in RULES else "Any rule",
            "flagged": flagged,
            "true_positives": tp,
            "false_positives": fp,
            "precision": precision,
            "recall": recall,
            "lift_vs_base_rate": precision / base_rate if flagged and base_rate else np.nan,
        })
    out = pd.DataFrame(rows)
    out.attrs["n_transactions"] = len(tx)
    out.attrs["n_laundering"] = int(y.sum())
    out.attrs["base_rate"] = float(base_rate)
    return out


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--file", type=Path, default=PROJECT_ROOT / "data" / "raw" / "HI-Small_Trans.csv")
    parser.add_argument("--nrows", type=int, default=None, help="read only the first N rows (for a quick run)")
    parser.add_argument("--out", type=Path, default=PROJECT_ROOT / "outputs" / "aml_rule_evaluation.csv")
    args = parser.parse_args()
    if not args.file.exists():
        raise SystemExit(f"{args.file} not found. Download HI-Small_Trans.csv from Kaggle (see data/README.md).")
    tx = load_ibm(args.file, nrows=args.nrows)
    res = evaluate(tx, apply_rules(tx))
    args.out.parent.mkdir(parents=True, exist_ok=True)
    res.to_csv(args.out, index=False)
    print(f"transactions: {res.attrs['n_transactions']:,}  laundering: {res.attrs['n_laundering']:,} "
          f"(base rate {res.attrs['base_rate']:.4%})")
    print(res.to_string(index=False, float_format=lambda v: f"{v:.4f}"))


if __name__ == "__main__":
    main()
