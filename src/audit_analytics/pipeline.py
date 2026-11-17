"""Run the full audit-analytics pipeline and write every output from real results.

Steps: generate (or reuse) the synthetic ledger -> completeness checks -> control tests ->
known-answer validation -> Benford -> charts -> workpapers -> findings memo.

Usage:
    python -m audit_analytics.pipeline            # reuse data/generated if present
    python -m audit_analytics.pipeline --regenerate --seed 2027
"""

from __future__ import annotations

import argparse
from datetime import date
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import pandas as pd  # noqa: E402

from . import PROJECT_ROOT  # noqa: E402
from .analytics import benford, completeness_checks, load_tables, run_all_tests  # noqa: E402
from .controls import CONTROL_TESTS  # noqa: E402
from .generate_ledger import generate, write  # noqa: E402

DATA = PROJECT_ROOT / "data" / "generated"
OUT = PROJECT_ROOT / "outputs"
IMG = PROJECT_ROOT / "images"
WP = PROJECT_ROOT / "workpapers"
REPORTS = PROJECT_ROOT / "reports"

RATING_ORDER = {"High": 0, "Medium": 1, "Low": 2}


def validate(exc: pd.DataFrame, planted: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for t in CONTROL_TESTS:
        got = set(exc.loc[exc.test_id == t.test_id, "payment_id"])
        expected = set(planted.loc[planted.issue_type.isin(t.planted_issue.split("|")), "payment_id"])
        extra = got - expected
        extra_planted = extra & set(planted.payment_id)
        rows.append({
            "test_id": t.test_id,
            "planted": len(expected),
            "found": len(got & expected),
            "missed": len(expected - got),
            "extra_other_planted": len(extra_planted),
            "extra_clean": len(extra - extra_planted),
        })
    return pd.DataFrame(rows)


def summarise(exc: pd.DataFrame, population: int, validation: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for t in CONTROL_TESTS:
        e = exc[exc.test_id == t.test_id]
        rows.append({
            "test_id": t.test_id, "name": t.name, "kind": t.kind, "rating": t.rating,
            "population": population, "exceptions": len(e),
            "exception_rate": len(e) / population, "exception_amount": round(e.amount.sum(), 2),
        })
    return pd.DataFrame(rows).merge(validation, on="test_id")


# ---------------------------------------------------------------------------
# Charts
# ---------------------------------------------------------------------------

COLORS = {"High": "#b8433a", "Medium": "#d08a2c", "Low": "#6b8fb5"}


def chart_exceptions(summary: pd.DataFrame, path: Path) -> None:
    s = summary.iloc[::-1]
    fig, ax = plt.subplots(figsize=(8, 4.6))
    bars = ax.barh(s.test_id + "  " + s.name, s.exceptions, color=[COLORS[r] for r in s.rating])
    ax.bar_label(bars, padding=3, fontsize=9)
    ax.set_xlabel("Exceptions (count)")
    ax.set_title("Exceptions by control test (synthetic data)", loc="left", fontsize=12)
    handles = [plt.Rectangle((0, 0), 1, 1, color=c) for c in COLORS.values()]
    ax.set_xlim(0, s.exceptions.max() * 1.45)
    ax.legend(handles, [f"{k} rating" for k in COLORS], frameon=False, loc="center right")
    ax.spines[["top", "right"]].set_visible(False)
    fig.tight_layout()
    fig.savefig(path, dpi=150)
    plt.close(fig)


def chart_benford(table: pd.DataFrame, path: Path, mad: float, conclusion: str) -> None:
    fig, ax = plt.subplots(figsize=(8, 4))
    ax.bar(table.digit, table.observed_pct, color="#6b8fb5", label="Observed")
    ax.plot(table.digit, table.expected_pct, "o-", color="#b8433a", label="Benford expected")
    ax.set_xticks(table.digit)
    ax.set_xlabel("First digit of payment amount")
    ax.set_ylabel("Share of payments")
    ax.yaxis.set_major_formatter(matplotlib.ticker.PercentFormatter(1.0, decimals=0))
    ax.set_title(f"First-digit test: MAD = {mad:.4f} ({conclusion})", loc="left", fontsize=12)
    ax.legend(frameon=False)
    ax.spines[["top", "right"]].set_visible(False)
    fig.tight_layout()
    fig.savefig(path, dpi=150)
    plt.close(fig)


def chart_monthly(exc: pd.DataFrame, path: Path) -> None:
    e = exc.drop_duplicates("payment_id").copy()
    e["month"] = pd.to_datetime(e.posted_at).dt.to_period("M").astype(str)
    m = e.groupby("month").size().reindex(
        [str(p) for p in pd.period_range("2025-01", "2025-12", freq="M")], fill_value=0)
    fig, ax = plt.subplots(figsize=(8, 3.4))
    ax.bar(m.index.str[5:], m.values, color="#6b8fb5")
    ax.set_xlabel("Month of 2025")
    ax.set_ylabel("Payments with 1+ exception")
    ax.set_title("Flagged payments by month", loc="left", fontsize=12)
    ax.spines[["top", "right"]].set_visible(False)
    fig.tight_layout()
    fig.savefig(path, dpi=150)
    plt.close(fig)


# ---------------------------------------------------------------------------
# Workpapers and memo
# ---------------------------------------------------------------------------


def md_table(df: pd.DataFrame) -> str:
    cols = list(df.columns)
    lines = ["| " + " | ".join(cols) + " |", "|" + "---|" * len(cols)]
    for _, r in df.iterrows():
        lines.append("| " + " | ".join(str(r[c]).replace("|", "/") for c in cols) + " |")
    return "\n".join(lines)


def write_workpaper(t, exc: pd.DataFrame, row: pd.Series, population_note: str, run_date: str) -> None:
    e = exc[exc.test_id == t.test_id].sort_values("posted_at")
    sample = e.head(10)[["payment_id", "vendor_id", "amount", "posted_at", "detail"]].copy()
    sample["amount"] = sample.amount.map("{:,.2f}".format)
    procedure_ref = (f"[`sql/control_tests/{t.sql_file}`](../sql/control_tests/{t.sql_file})" if t.sql_file
                     else "`vendor_outliers()` in [`src/audit_analytics/analytics.py`](../src/audit_analytics/analytics.py)")
    if row.exceptions == 0:
        conclusion = "No exceptions noted. The control operated as designed for this population."
    elif t.kind == "Control":
        conclusion = (f"Exceptions noted ({row.exceptions}). In this synthetic scenario the control did not "
                      "operate effectively for the flagged payments, pending follow-up.")
    else:
        conclusion = (f"{row.exceptions} payments flagged for follow-up. A flag on a risk indicator is not by "
                      "itself a control failure; each item needs to be vouched to support.")
    validation = (f"Known-answer check: {row.found} of {row.planted} planted issues found, {row.missed} missed. "
                  f"Other flags: {row.extra_other_planted} were planted issues of another type, "
                  f"{row.extra_clean} were clean records.")
    text = f"""# {t.test_id} {t.name}

| Field | Detail |
|---|---|
| Test type | {"Key control test" if t.kind == "Control" else "Risk indicator (analytics flag)"} |
| Risk rating | {t.rating} |
| Prepared | Generated by `audit_analytics.pipeline` on {run_date} |
| Data | Synthetic accounts-payable ledger (not real company data) |

## Control objective
{t.objective}

## Risk
{t.risk}

## Population
{population_note}

## Procedure
{t.procedure}

Query / code: {procedure_ref}

## Results
- Exceptions: **{row.exceptions}** of {row.population:,} payments ({row.exception_rate:.2%})
- Amount of flagged payments: CAD {row.exception_amount:,.2f}
- {validation}

{"First 10 exceptions (full list in `outputs/exceptions.csv`):" if len(e) else ""}

{md_table(sample) if len(e) else "_None._"}

## Conclusion
{conclusion}

## Follow-up procedure
{t.follow_up}

## Recommended management action
{t.management_action}
"""
    (WP / f"{t.test_id}_{t.name.lower().replace(' ', '_').replace('-', '_')}.md").write_text(text)


def write_memo(summary: pd.DataFrame, completeness: pd.DataFrame, bf, run_date: str, aml: pd.DataFrame | None) -> None:
    s = summary.sort_values(["rating", "test_id"], key=lambda c: c.map(RATING_ORDER) if c.name == "rating" else c)
    tbl = s[["test_id", "name", "kind", "rating", "exceptions", "exception_amount"]].copy()
    tbl["exception_amount"] = tbl.exception_amount.map("{:,.2f}".format)
    tbl.columns = ["Test", "Name", "Type", "Rating", "Exceptions", "Flagged amount (CAD)"]
    val = summary[["test_id", "planted", "found", "missed", "extra_other_planted", "extra_clean"]]
    val.columns = ["Test", "Planted", "Found", "Missed", "Other planted issues flagged", "Clean records flagged"]
    high = s[(s.rating == "High") & (s.exceptions > 0)]
    findings = "\n".join(
        f"{i}. **{r.name} ({r.test_id})**: {r.exceptions} payments, CAD {r.exception_amount:,.2f}. "
        f"{next(t for t in CONTROL_TESTS if t.test_id == r.test_id).management_action}"
        for i, r in enumerate(high.itertuples(), 1))
    if aml is not None:
        a = aml.copy()
        for c in ["precision", "recall"]:
            a[c] = a[c].map(lambda v: "n/a" if pd.isna(v) else f"{v:.2%}")
        a["lift_vs_base_rate"] = a.lift_vs_base_rate.map(lambda v: "n/a" if pd.isna(v) else f"{v:.1f}x")
        aml_section = ("Rules from `src/audit_analytics/aml.py`, run on the IBM synthetic AML data "
                       "(results in `outputs/aml_rule_evaluation.csv`).\n\n" + md_table(a))
    else:
        aml_section = ("_Not run yet._ Download `HI-Small_Trans.csv` (see `data/README.md`) and run "
                       "`python -m audit_analytics.aml`, then re-run the pipeline. No AML results are reported "
                       "until they come from a real run.")
    text = f"""# Audit findings memo: accounts-payable payment controls

**Scope:** synthetic accounts-payable ledger, payments posted 1 Jan to 31 Dec 2025
**Prepared:** {run_date}, generated from pipeline outputs
**Important:** all data is synthetic and was generated with planted issues. This memo demonstrates
audit-analytics methods. It is not an audit opinion and does not describe any real organisation.

## 1. Summary
Ten tests were run on the full population of {summary.population.iloc[0]:,} payments rather than a sample.
{int((s.kind == 'Control').sum())} tests check key controls and {int((s.kind == 'Indicator').sum())} are risk indicators
that need follow-up before any conclusion. {len(high)} high-rated tests returned exceptions.

{md_table(tbl)}

## 2. Key findings (high rating)
{findings if findings else "No high-rated exceptions."}

Indicator flags (near-limit amounts, off-hours posting, round amounts, new-vendor payments and statistical
outliers) should be vouched to invoices and approvals before they are reported as findings.

## 3. Population completeness
Checks performed before testing:

{md_table(completeness)}

## 4. Did the tests work? Known-answer validation
The generator plants a known number of each issue into an otherwise clean ledger. A test passes only if it
finds every planted issue of its type. The outlier test (CT-10) is statistical, so it also flags
large payments planted for other tests and a few clean records; those are shown separately.

{md_table(val)}

## 5. Benford's Law (first digit)
{bf.n:,} payments of $10 or more. Chi-square = {bf.chi2:.2f} (8 df), p = {bf.p_value:.3f}; mean absolute deviation
= {bf.mad:.4f}, which is **{bf.conclusion.lower()}** on Nigrini's scale. The planted issues are too few to move
the overall distribution, so Benford is shown as a population-level screen, not as evidence about any payment.

![Benford first-digit test](../images/benford_first_digit.png)

## 6. Transaction-monitoring rules on labelled AML data
{aml_section}

## 7. Limitations
- Synthetic data: the clean population is built to pass every test, so real data would produce more noise.
- Thresholds (30-day duplicate window, 95% near-limit band, $50,000 new-vendor amount, z > 3.5) are
  illustrative and would be set with management in a real engagement.
- Tests find patterns in data; they do not show intent. Each exception needs follow-up evidence.
"""
    (REPORTS / "audit_findings_memo.md").write_text(text)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--regenerate", action="store_true")
    parser.add_argument("--seed", type=int, default=2027)
    args = parser.parse_args()
    for d in (OUT, IMG, WP, REPORTS):
        d.mkdir(parents=True, exist_ok=True)

    if args.regenerate or not (DATA / "payments.csv").exists():
        write(generate(args.seed), DATA)

    tables = load_tables(DATA)
    planted = pd.read_csv(DATA / "planted_issues.csv")
    payments = tables["payments"]
    population = len(payments)
    run_date = date.today().isoformat()

    completeness = completeness_checks(tables)
    exc = run_all_tests(tables)
    validation = validate(exc, planted)
    summary = summarise(exc, population, validation)
    bf = benford(payments.amount)

    completeness.to_csv(OUT / "completeness_checks.csv", index=False)
    exc.to_csv(OUT / "exceptions.csv", index=False)
    summary.to_csv(OUT / "test_summary.csv", index=False)
    bf.table.to_csv(OUT / "benford_first_digit.csv", index=False)

    chart_exceptions(summary, IMG / "exceptions_by_test.png")
    chart_benford(bf.table, IMG / "benford_first_digit.png", bf.mad, bf.conclusion)
    chart_monthly(exc, IMG / "flagged_payments_by_month.png")

    population_note = (f"All {population:,} payments posted from {payments.posted_at.min()[:10]} to "
                       f"{payments.posted_at.max()[:10]} (CAD {payments.amount.sum():,.2f}); full population, no sampling. "
                       "Completeness checks: `outputs/completeness_checks.csv`.")
    for t in CONTROL_TESTS:
        write_workpaper(t, exc, summary.set_index("test_id").loc[t.test_id], population_note, run_date)

    aml_path = OUT / "aml_rule_evaluation.csv"
    aml = pd.read_csv(aml_path) if aml_path.exists() else None
    write_memo(summary, completeness, bf, run_date, aml)

    print(summary[["test_id", "name", "exceptions", "planted", "found", "missed",
                   "extra_other_planted", "extra_clean"]].to_string(index=False))
    print(f"Benford MAD {bf.mad:.4f} ({bf.conclusion}); exceptions written to {OUT / 'exceptions.csv'}")


if __name__ == "__main__":
    main()
