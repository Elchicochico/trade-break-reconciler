"""
Automated Trade Break & Corporate Action Reconciler — Ops Dashboard
-----------------------------------------------------------------
Interactive Streamlit UI for uploading OMS, Custodian, and Corporate Action CSVs,
filtering breaks by escalation priority, and downloading the break report.

Setup & Run:
    pip3 install streamlit
    python3 -m streamlit run reconciler_app.py
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import streamlit as st

import trade_reconciler as rec

st.set_page_config(
    page_title="Trade Break & Corporate Action Reconciler",
    page_icon="🛡️",
    layout="wide",
)

st.title("🛡️ Trade Break & Corporate Action Reconciler")
st.caption(
    "Upload your OMS blotter, Custodian report, and Corporate Actions feed "
    "(or test immediately with the built-in sample files)."
)

# Sidebar file uploads & tolerances
with st.sidebar:
    st.header("1. Upload Blotters (Optional)")
    oms_file = st.file_uploader("OMS Trades CSV", type=["csv"])
    cust_file = st.file_uploader("Custodian Trades CSV", type=["csv"])
    ca_file = st.file_uploader("Corporate Actions CSV", type=["csv"])

    st.header("2. Filter Breaks")
    selected_priorities = st.multiselect(
        "Escalation Priority",
        options=["CRITICAL", "HIGH", "MEDIUM", "LOW", "NONE"],
        default=["CRITICAL", "HIGH", "MEDIUM", "LOW"],
    )

data_dir = Path(".")
if not (data_dir / "oms_trades.csv").exists():
    rec.create_sample_data(data_dir)

oms_df = pd.read_csv(oms_file) if oms_file else pd.read_csv(data_dir / "oms_trades.csv")
cust_df = pd.read_csv(cust_file) if cust_file else pd.read_csv(data_dir / "custodian_trades.csv")
ca_df = pd.read_csv(ca_file) if ca_file else pd.read_csv(data_dir / "corporate_actions.csv")

splits = {
    row["ticker"]: float(row["ratio"])
    for _, row in ca_df.iterrows()
    if str(row["action_type"]).upper() == "SPLIT"
}

merged = pd.merge(oms_df, cust_df, on="trade_id", how="outer", suffixes=("_oms", "_cust"))
results = merged.apply(lambda r: rec.classify_break(r, splits), axis=1, result_type="expand")
merged[["status", "details", "priority"]] = results

merged["ticker"] = merged["ticker_oms"].fillna(merged["ticker_cust"])
merged["account"] = merged["account_oms"].fillna(merged["account_cust"])
merged["oms_notional"] = (merged["quantity_oms"] * merged["price_oms"]).fillna(0.0)

priority_rank = {"CRITICAL": 0, "HIGH": 1, "MEDIUM": 2, "LOW": 3, "NONE": 4}
merged["_rank"] = merged["priority"].map(priority_rank)
merged = merged.sort_values(["_rank", "oms_notional"], ascending=[True, False]).drop(columns=["_rank"])

report_cols = [
    "trade_id",
    "account",
    "ticker",
    "status",
    "priority",
    "details",
    "quantity_oms",
    "quantity_cust",
    "price_oms",
    "price_cust",
    "settle_date_oms",
    "settle_date_cust",
]
report = merged[report_cols]

# KPI summary row
total_trades = len(report)
breaks_df = report[report["status"] != "MATCHED"]
critical_count = int((report["priority"] == "CRITICAL").sum())
match_rate = ((total_trades - len(breaks_df)) / total_trades * 100) if total_trades else 0.0

c1, c2, c3, c4 = st.columns(4)
c1.metric("Total Trades", total_trades)
c2.metric("Open Breaks", len(breaks_df))
c3.metric("Critical Escalations", critical_count)
c4.metric("Match Rate", f"{match_rate:.1f}%")

# Break breakdown chart
if not breaks_df.empty:
    st.subheader("Breaks by Type")
    st.bar_chart(breaks_df["status"].value_counts())

# Filtered break table + download
filtered = report[report["priority"].isin(selected_priorities)]
st.subheader(f"Escalation Queue ({len(filtered)} rows)")
st.dataframe(filtered, width="stretch", hide_index=True)

csv_bytes = filtered.to_csv(index=False).encode("utf-8")
st.download_button(
    label="Download Filtered Break Report (CSV)",
    data=csv_bytes,
    file_name="reconciliation_report.csv",
    mime="text/csv",
)