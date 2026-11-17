"""Generate a synthetic accounts-payable ledger with planted control exceptions.

Everything produced here is synthetic. No real company, bank, vendor or person is
represented. The generator first builds a "clean" population that passes every
control test, then plants a known number of exceptions of each type, each made by
changing one attribute of an otherwise clean payment. The planted IDs are written
to ``planted_issues.csv`` so the control tests can be checked against a known answer.

Usage:
    python -m audit_analytics.generate_ledger --seed 2027 --out data/generated
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from pathlib import Path

import numpy as np
import pandas as pd

PERIOD_START = date(2025, 1, 1)
PERIOD_END = date(2025, 12, 31)

N_CLEAN_PAYMENTS = 5000
N_VENDORS = 150

# Number of planted exceptions per issue type (SPLIT counts groups, not payments).
PLANTED = {
    "DUPLICATE": 12,
    "SOD": 8,
    "EXCEEDS_LIMIT": 6,
    "JUST_BELOW_LIMIT": 10,
    "SPLIT": 5,
    "OFF_HOURS": 15,
    "ROUND_AMOUNT": 10,
    "NEW_VENDOR_LARGE": 4,
    "INACTIVE_VENDOR": 3,
    "UNKNOWN_VENDOR": 3,
    "OUTLIER": 5,
}

# Clean amounts stay below this share of the approver's limit, so the
# "just below the limit" zone (95%-100%) only contains planted payments.
CLEAN_LIMIT_SHARE = 0.90


@dataclass
class Ledger:
    employees: pd.DataFrame
    vendors: pd.DataFrame
    payments: pd.DataFrame
    planted: pd.DataFrame
    rows: list = field(default_factory=list)


def business_days(start: date, end: date) -> list[date]:
    days = pd.bdate_range(start, end)
    return [d.date() for d in days]


def build_employees() -> pd.DataFrame:
    rows = []
    for i in range(1, 9):
        rows.append((f"E{i:03d}", f"AP Clerk {i}", "AP Clerk", True, 0))
    for i, limit in enumerate([50_000, 50_000, 50_000, 50_000], start=9):
        rows.append((f"E{i:03d}", f"AP Supervisor {i - 8}", "AP Supervisor", True, limit))
    for i, limit in enumerate([100_000, 100_000, 100_000, 250_000, 250_000, 250_000], start=13):
        rows.append((f"E{i:03d}", f"Finance Manager {i - 12}", "Finance Manager", False, limit))
    for i, limit in enumerate([1_000_000, 1_000_000], start=19):
        rows.append((f"E{i:03d}", f"Controller {i - 18}", "Controller", False, limit))
    return pd.DataFrame(
        rows, columns=["employee_id", "employee_name", "role", "can_create", "approval_limit"]
    )


def build_vendors(rng: np.random.Generator) -> pd.DataFrame:
    rows = []
    for i in range(1, N_VENDORS + 1):
        created = date(2018, 1, 1) + timedelta(days=int(rng.integers(0, 365 * 6)))
        # Each vendor gets its own typical invoice size (log scale).
        typical = float(np.exp(rng.normal(np.log(5000), 0.8)))
        rows.append((f"V{i:04d}", f"Synthetic Vendor {i:03d}", created.isoformat(), "Active", None, typical))
    return pd.DataFrame(
        rows,
        columns=["vendor_id", "vendor_name", "created_date", "status", "inactive_date", "typical_amount"],
    )


def random_time(rng: np.random.Generator, day: date, start_hour: int = 8, end_hour: int = 18) -> datetime:
    seconds = int(rng.integers(start_hour * 3600, end_hour * 3600))
    return datetime.combine(day, datetime.min.time()) + timedelta(seconds=seconds)


def is_round_thousand(amount: float) -> bool:
    return round(amount, 2) == round(amount) and int(round(amount)) % 1000 == 0


def generate(seed: int = 2027) -> Ledger:
    rng = np.random.default_rng(seed)
    employees = build_employees()
    vendors = build_vendors(rng)
    bdays = business_days(PERIOD_START, PERIOD_END)

    creators = employees[employees.can_create]
    approvers = employees[employees.approval_limit > 0]

    used_vendor_day: set[tuple[str, date]] = set()
    used_vendor_amount: set[tuple[str, float]] = set()
    invoice_counter = {v: 10_000 for v in vendors.vendor_id}

    def next_invoice(vendor_id: str) -> str:
        invoice_counter[vendor_id] += int(rng.integers(1, 40))
        return f"INV-{vendor_id}-{invoice_counter[vendor_id]}"

    def pick_approver(amount: float, exclude: str | None = None) -> pd.Series:
        ok = approvers[(approvers.approval_limit * CLEAN_LIMIT_SHARE > amount)]
        if exclude is not None:
            ok = ok[ok.employee_id != exclude]
        return ok.iloc[int(rng.integers(0, len(ok)))]

    def clean_amount(vendor: pd.Series) -> float:
        while True:
            amt = float(np.exp(rng.normal(np.log(vendor.typical_amount), 0.6)))
            amt = round(min(max(amt, 50.0), 400_000.0), 2)
            # avoid whole-dollar amounts so round-amount flags are only planted ones
            if round(amt) == amt:
                continue
            if (vendor.vendor_id, amt) in used_vendor_amount:
                continue
            return amt

    payments = []

    def add(vendor_id, invoice_no, amount, created_by, approved_by, posted_at, method="EFT"):
        payments.append(
            {
                "vendor_id": vendor_id,
                "invoice_no": invoice_no,
                "invoice_date": (posted_at.date() - timedelta(days=int(rng.integers(5, 40)))).isoformat(),
                "amount": round(float(amount), 2),
                "currency": "CAD",
                "payment_method": method,
                "created_by": created_by,
                "approved_by": approved_by,
                "posted_at": posted_at.isoformat(sep=" "),
                "_tag": None,
                "_group": None,
            }
        )
        return len(payments) - 1

    # ---- clean population -------------------------------------------------
    active = vendors.reset_index(drop=True)
    while len(payments) < N_CLEAN_PAYMENTS:
        vendor = active.iloc[int(rng.integers(0, len(active)))]
        day = bdays[int(rng.integers(0, len(bdays)))]
        if (vendor.vendor_id, day) in used_vendor_day:
            continue
        amount = clean_amount(vendor)
        creator = creators.iloc[int(rng.integers(0, len(creators)))]
        approver = pick_approver(amount, exclude=creator.employee_id)
        used_vendor_day.add((vendor.vendor_id, day))
        used_vendor_amount.add((vendor.vendor_id, amount))
        add(vendor.vendor_id, next_invoice(vendor.vendor_id), amount, creator.employee_id,
            approver.employee_id, random_time(rng, day))

    clean_idx = list(range(len(payments)))
    locked: set[int] = set()

    def take_clean() -> int:
        """Pick a clean payment that has not been modified yet."""
        while True:
            i = clean_idx[int(rng.integers(0, len(clean_idx)))]
            if payments[i]["_tag"] is None and i not in locked:
                return i

    def free_day_for(vendor_id: str, near: date | None = None) -> date:
        while True:
            if near is None:
                d = bdays[int(rng.integers(0, len(bdays)))]
            else:
                d = near + timedelta(days=int(rng.integers(1, 15)))
                if d.weekday() >= 5 or d > PERIOD_END:
                    continue
            if (vendor_id, d) not in used_vendor_day:
                used_vendor_day.add((vendor_id, d))
                return d

    emp = employees.set_index("employee_id")

    # ---- planted exceptions ----------------------------------------------
    # 1. Duplicate payments: same vendor, invoice and amount paid again within ~2 weeks.
    while sum(p["_tag"] == "DUPLICATE" for p in payments) < PLANTED["DUPLICATE"]:
        j = take_clean()
        src = payments[j]
        src_day = datetime.fromisoformat(src["posted_at"]).date()
        if src_day > PERIOD_END - timedelta(days=20):
            continue
        locked.add(j)  # the original must stay unchanged so the pair still matches
        day = free_day_for(src["vendor_id"], near=src_day)
        creator = creators.iloc[int(rng.integers(0, len(creators)))]
        approver = pick_approver(src["amount"], exclude=creator.employee_id)
        i = add(src["vendor_id"], src["invoice_no"], src["amount"], creator.employee_id,
                approver.employee_id, random_time(rng, day))
        payments[i]["_tag"] = "DUPLICATE"

    # 2. Segregation of duties: a supervisor creates and approves the same payment.
    supervisors = employees[employees.role == "AP Supervisor"]
    for _ in range(PLANTED["SOD"]):
        i = take_clean()
        sup = supervisors.iloc[int(rng.integers(0, len(supervisors)))]
        payments[i]["amount"] = min(payments[i]["amount"], round(sup.approval_limit * 0.5 - 0.37, 2))
        payments[i]["created_by"] = sup.employee_id
        payments[i]["approved_by"] = sup.employee_id
        payments[i]["_tag"] = "SOD"

    # 3. Approved above the approver's authority limit.
    for _ in range(PLANTED["EXCEEDS_LIMIT"]):
        i = take_clean()
        appr = emp.loc[payments[i]["approved_by"]]
        while appr.approval_limit > 250_000:
            i = take_clean()
            appr = emp.loc[payments[i]["approved_by"]]
        payments[i]["amount"] = round(appr.approval_limit * rng.uniform(1.05, 1.6) + 0.43, 2)
        payments[i]["_tag"] = "EXCEEDS_LIMIT"

    # 4. Just below the approver's limit (95%-100%).
    for _ in range(PLANTED["JUST_BELOW_LIMIT"]):
        i = take_clean()
        appr = emp.loc[payments[i]["approved_by"]]
        payments[i]["amount"] = round(appr.approval_limit * rng.uniform(0.955, 0.995) + 0.29, 2)
        payments[i]["_tag"] = "JUST_BELOW_LIMIT"

    # 5. Split payments: one purchase broken into 2-3 same-day payments that are each
    #    under the approver's limit but together exceed it.
    for g in range(PLANTED["SPLIT"]):
        vendor = active.iloc[int(rng.integers(0, len(active)))]
        appr = approvers[approvers.approval_limit <= 250_000].iloc[
            int(rng.integers(0, len(approvers[approvers.approval_limit <= 250_000])))]
        creator = creators[creators.employee_id != appr.employee_id].iloc[0]
        day = free_day_for(vendor.vendor_id)
        n = int(rng.integers(2, 4))
        for _ in range(n):
            amt = round(appr.approval_limit * rng.uniform(0.6, 0.85) + 0.17, 2)
            i = add(vendor.vendor_id, next_invoice(vendor.vendor_id), amt, creator.employee_id,
                    appr.employee_id, random_time(rng, day))
            payments[i]["_tag"] = "SPLIT"
            payments[i]["_group"] = f"SPLIT-{g + 1}"

    # 6. Posted on a weekend or late at night.
    for k in range(PLANTED["OFF_HOURS"]):
        i = take_clean()
        posted = datetime.fromisoformat(payments[i]["posted_at"])
        if k % 2 == 0:  # move to the following Saturday/Sunday
            shift = (5 - posted.weekday()) + int(rng.integers(0, 2))
            new_day = posted.date() + timedelta(days=shift)
            if new_day > PERIOD_END:
                new_day = posted.date() - timedelta(days=posted.weekday() + 1)  # previous Sunday
            new_posted = random_time(rng, new_day, 9, 17)
        else:  # same weekday, between 22:00 and 04:59
            hour = int(rng.choice([22, 23, 0, 1, 2, 3, 4]))
            new_posted = datetime.combine(posted.date(), datetime.min.time()) + timedelta(
                hours=hour, minutes=int(rng.integers(0, 60)))
        payments[i]["posted_at"] = new_posted.isoformat(sep=" ")
        payments[i]["_tag"] = "OFF_HOURS"

    # 7. Round-thousand amounts of $5,000 or more.
    for _ in range(PLANTED["ROUND_AMOUNT"]):
        i = take_clean()
        appr = emp.loc[payments[i]["approved_by"]]
        cap = int(appr.approval_limit * CLEAN_LIMIT_SHARE // 1000)
        payments[i]["amount"] = float(1000 * int(rng.integers(5, max(min(cap, 40), 6))))
        payments[i]["_tag"] = "ROUND_AMOUNT"

    # 8. Large payment to a vendor created within the last 30 days.
    for k in range(PLANTED["NEW_VENDOR_LARGE"]):
        created = date(2025, 3, 1) + timedelta(days=int(rng.integers(0, 240)))
        vid = f"V{N_VENDORS + k + 1:04d}"
        vendors.loc[len(vendors)] = [vid, f"Synthetic Vendor {N_VENDORS + k + 1:03d}",
                                     created.isoformat(), "Active", None, 60_000.0]
        invoice_counter[vid] = 10_000
        day = created + timedelta(days=int(rng.integers(3, 25)))
        while day.weekday() >= 5:
            day += timedelta(days=1)
        amt = round(rng.uniform(60_000, 200_000) + 0.61, 2)
        appr = approvers[approvers.approval_limit * CLEAN_LIMIT_SHARE > amt].iloc[0]
        creator = creators.iloc[int(rng.integers(0, len(creators)))]
        used_vendor_day.add((vid, day))
        i = add(vid, next_invoice(vid), amt, creator.employee_id, appr.employee_id, random_time(rng, day))
        payments[i]["_tag"] = "NEW_VENDOR_LARGE"

    # 9. Payment to a vendor after it was deactivated in the vendor master.
    inactive_ids = []
    for k in range(PLANTED["INACTIVE_VENDOR"]):
        vid = f"V{N_VENDORS + PLANTED['NEW_VENDOR_LARGE'] + k + 1:04d}"
        inactive_on = date(2025, 2, 1) + timedelta(days=int(rng.integers(0, 200)))
        vendors.loc[len(vendors)] = [vid, f"Synthetic Vendor {N_VENDORS + PLANTED['NEW_VENDOR_LARGE'] + k + 1:03d}",
                                     "2019-06-01", "Inactive", inactive_on.isoformat(), 3000.0]
        invoice_counter[vid] = 10_000
        inactive_ids.append(vid)
        day = inactive_on + timedelta(days=int(rng.integers(10, 60)))
        while day.weekday() >= 5:
            day += timedelta(days=1)
        amt = round(rng.uniform(1_500, 9_000) + 0.13, 2)
        creator = creators.iloc[int(rng.integers(0, len(creators)))]
        appr = pick_approver(amt, exclude=creator.employee_id)
        i = add(vid, next_invoice(vid), amt, creator.employee_id, appr.employee_id, random_time(rng, day))
        payments[i]["_tag"] = "INACTIVE_VENDOR"

    # 10. Payment to a vendor ID that does not exist in the vendor master.
    for k in range(PLANTED["UNKNOWN_VENDOR"]):
        vid = f"V9{k + 1:03d}"
        day = bdays[int(rng.integers(0, len(bdays)))]
        amt = round(rng.uniform(2_000, 15_000) + 0.07, 2)
        creator = creators.iloc[int(rng.integers(0, len(creators)))]
        appr = pick_approver(amt, exclude=creator.employee_id)
        i = add(vid, f"INV-{vid}-{10_000 + k}", amt, creator.employee_id, appr.employee_id, random_time(rng, day))
        payments[i]["_tag"] = "UNKNOWN_VENDOR"

    # 11. Statistical outliers: far above the vendor's usual invoice size.
    for _ in range(PLANTED["OUTLIER"]):
        i = take_clean()
        vend = vendors.set_index("vendor_id").loc[payments[i]["vendor_id"]]
        amt = round(min(vend.typical_amount * rng.uniform(25, 40), 220_000) + 0.53, 2)
        top = approvers[approvers.approval_limit == 250_000]
        appr = top[top.employee_id != payments[i]["created_by"]].iloc[0]
        payments[i]["amount"] = amt
        payments[i]["approved_by"] = appr.employee_id
        payments[i]["_tag"] = "OUTLIER"

    # ---- finalise ---------------------------------------------------------
    df = pd.DataFrame(payments).sort_values(["posted_at", "vendor_id"]).reset_index(drop=True)
    df.insert(0, "payment_id", [f"PAY-{i + 1:06d}" for i in range(len(df))])
    planted = df.loc[df._tag.notna(), ["payment_id", "_tag", "_group"]].rename(
        columns={"_tag": "issue_type", "_group": "group_id"})
    payments_out = df.drop(columns=["_tag", "_group"])
    vendors_out = vendors.drop(columns=["typical_amount"])
    return Ledger(employees=employees, vendors=vendors_out, payments=payments_out, planted=planted)


def write(ledger: Ledger, out: Path) -> None:
    out.mkdir(parents=True, exist_ok=True)
    ledger.employees.to_csv(out / "employees.csv", index=False)
    ledger.vendors.to_csv(out / "vendors.csv", index=False)
    ledger.payments.to_csv(out / "payments.csv", index=False)
    ledger.planted.to_csv(out / "planted_issues.csv", index=False)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seed", type=int, default=2027)
    parser.add_argument("--out", type=Path, default=Path("data/generated"))
    args = parser.parse_args()
    ledger = generate(args.seed)
    write(ledger, args.out)
    counts = ledger.planted.issue_type.value_counts().sort_index()
    print(f"payments: {len(ledger.payments):,}  vendors: {len(ledger.vendors)}  employees: {len(ledger.employees)}")
    print("planted payments by issue type:")
    print(counts.to_string())


if __name__ == "__main__":
    main()
