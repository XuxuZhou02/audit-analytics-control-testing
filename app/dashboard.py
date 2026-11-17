"""Exception dashboard. Run after the pipeline:  streamlit run app/dashboard.py"""

import sys
from pathlib import Path

import pandas as pd
import streamlit as st

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from audit_analytics.controls import BY_ID  # noqa: E402

OUT = ROOT / "outputs"

st.set_page_config(page_title="AP Control Testing", layout="wide")
st.title("Accounts-payable control testing")
st.caption("Synthetic data with planted issues. A demonstration of audit-analytics methods, not an audit opinion.")

if not (OUT / "exceptions.csv").exists():
    st.error("No outputs yet. Run `python -m audit_analytics.pipeline` first.")
    st.stop()

summary = pd.read_csv(OUT / "test_summary.csv")
exc = pd.read_csv(OUT / "exceptions.csv")
exc["rating"] = exc.test_id.map(lambda t: BY_ID[t].rating)
exc["test_name"] = exc.test_id.map(lambda t: BY_ID[t].name)
exc["month"] = pd.to_datetime(exc.posted_at).dt.to_period("M").astype(str)

c1, c2, c3, c4 = st.columns(4)
c1.metric("Payments tested", f"{summary.population.iloc[0]:,}")
c2.metric("Flagged payments", f"{exc.payment_id.nunique():,}")
c3.metric("High-rated flags", f"{exc[exc.rating == 'High'].payment_id.nunique():,}")
c4.metric("Flagged CAD", f"{exc.drop_duplicates('payment_id').amount.sum() / 1e6:,.1f}M")

with st.sidebar:
    st.header("Filters")
    ratings = st.multiselect("Rating", ["High", "Medium", "Low"], default=["High", "Medium", "Low"])
    tests = st.multiselect("Test", summary.test_id.tolist(), default=summary.test_id.tolist(),
                           format_func=lambda t: f"{t} {BY_ID[t].name}")
view = exc[exc.rating.isin(ratings) & exc.test_id.isin(tests)]

left, right = st.columns(2)
with left:
    st.subheader("Exceptions by test")
    st.bar_chart(view.groupby("test_id").size(), horizontal=True)
    st.caption("Test names are in the sidebar and the summary table below.")
with right:
    st.subheader("Exceptions by month")
    st.bar_chart(view.groupby("month").size())

st.subheader("Test summary and known-answer validation")
st.dataframe(summary[["test_id", "name", "kind", "rating", "exceptions", "exception_amount",
                      "planted", "found", "missed", "extra_other_planted", "extra_clean"]],
             hide_index=True, use_container_width=True)

st.subheader("Exception detail")
st.dataframe(view[["test_id", "rating", "payment_id", "vendor_id", "amount", "created_by", "approved_by",
                   "posted_at", "detail"]].sort_values(["test_id", "posted_at"]),
             hide_index=True, use_container_width=True)
st.download_button("Download filtered exceptions (CSV)", view.to_csv(index=False), "exceptions_filtered.csv")
