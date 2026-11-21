"""
Automated Trade Break & Corporate Action Reconciler
-------------------------------------------------
Compares an internal OMS trade blotter against a custodian settlement report,
checks a corporate actions feed for unapplied splits, classifies breaks,
and assigns an operational escalation priority.

Requirements:
    pip3 install pandas

Run:
    python3 trade_reconciler.py
"""

from __future__ import annotations

import argparse
from pathlib import Path

import pandas as pd

PRICE_TOLERANCE = 0.01  # $0.01 per share tolerance


def create_sample_data(data_dir: Path) -> None:
    """Generate realistic sample OMS, Custodian, and Corporate Action CSVs."""
    oms_rows = [
        {"trade_id": "T1001", "account": "FUND_A", "ticker": "AAPL", "side": "BUY", "quantity": 1000, "price": 225.50, "settle_date": "2026-11-23"},
        {"trade_id": "T1002", "account": "FUND_A", "ticker": "MSFT", "side": "SELL", "quantity": 500, "price": 420.00, "settle_date": "2026-11-23"},
        {"trade_id": "T1003", "account": "FUND_B", "ticker": "NVDA", "side": "BUY", "quantity": 200, "price": 140.00, "settle_date": "2026-11-23"},
        {"trade_id": "T1004", "account": "FUND_B", "ticker": "JPM", "side": "BUY", "quantity": 800, "price": 210.25, "settle_date": "2026-11-23"},
        {"trade_id": "T1005", "account": "FUND_A", "ticker": "SPY", "side": "SELL", "quantity": 1500, "price": 585.00, "settle_date": "2026-11-23"},
        {"trade_id": "T1006", "account": "FUND_C", "ticker": "AMZN", "side": "BUY", "quantity": 300, "price": 205.00, "settle_date": "2026-11-23"},
    ]

    custodian_rows = [
        # T1001: Clean match
        {"trade_id": "T1001", "account": "FUND_A", "ticker": "AAPL", "side": "BUY", "quantity": 1000, "price": 225.50, "settle_date": "2026-11-23"},
        # T1002: Price break ($420.00 vs $421.25)
        {"trade_id": "T1002", "account": "FUND_A", "ticker": "MSFT", "side": "SELL", "quantity": 500, "price": 421.25, "settle_date": "2026-11-23"},
        # T1003: Unapplied 2-for-1 split at custodian (400 shares @ $70 vs 200 @ $140)
        {"trade_id": "T1003", "account": "FUND_B", "ticker": "NVDA", "side": "BUY", "quantity": 400, "price": 70.00, "settle_date": "2026-11-23"},
        # T1004: Settlement date mismatch (T+2 vs T+1)
        {"trade_id": "T1004", "account": "FUND_B", "ticker": "JPM", "side": "BUY", "quantity": 800, "price": 210.25, "settle_date": "2026-11-24"},
        # T1005: Missing at custodian!
        # T1006: Quantity break (300 vs 250)
        {"trade_id": "T1006", "account": "FUND_C", "ticker": "AMZN", "side": "BUY", "quantity": 250, "price": 205.00, "settle_date": "2026-11-23"},
        # T1007: Unmatched trade reported only by custodian
        {"trade_id": "T1007", "account": "FUND_C", "ticker": "META", "side": "BUY", "quantity": 100, "price": 590.00, "settle_date": "2026-11-23"},
    ]

    corp_actions = [
        {"ticker": "NVDA", "action_type": "SPLIT", "ratio": 2.0, "effective_date": "2026-11-23"},
    ]

    pd.DataFrame(oms_rows).to_csv(data_dir / "oms_trades.csv", index=False)
    pd.DataFrame(custodian_rows).to_csv(data_dir / "custodian_trades.csv", index=False)
    pd.DataFrame(corp_actions).to_csv(data_dir / "corporate_actions.csv", index=False)


def classify_break(row: pd.Series, splits: dict[str, float]) -> tuple[str, str, str]:
    """
    Classify a reconciled trade row and return:
    (status, break_details, escalation_priority)
    """
    in_oms = pd.notna(row["quantity_oms"])
    in_cust = pd.notna(row["quantity_cust"])

    if in_oms and not in_cust:
        notional = row["quantity_oms"] * row["price_oms"]
        return ("MISSING_AT_CUSTODIAN", f"Not booked at custodian (${notional:,.0f})", "CRITICAL")

    if in_cust and not in_oms:
        notional = row["quantity_cust"] * row["price_cust"]
        return ("MISSING_AT_OMS", f"Unrecognized custodian trade (${notional:,.0f})", "CRITICAL")

    qty_oms, qty_cust = row["quantity_oms"], row["quantity_cust"]
    px_oms, px_cust = row["price_oms"], row["price_cust"]
    dt_oms, dt_cust = row["settle_date_oms"], row["settle_date_cust"]
    ticker = row["ticker_oms"]

    # Check if a quantity/price difference is explained by an unapplied corporate action
    if ticker in splits and qty_oms != qty_cust:
        ratio = splits[ticker]
        if qty_cust == qty_oms * ratio and abs(px_cust - (px_oms / ratio)) <= PRICE_TOLERANCE:
            return (
                "UNAPPLIED_CORP_ACTION",
                f"Custodian reflects {ratio:g}:1 split; OMS needs adjustment",
                "HIGH",
            )

    issues: list[str] = []
    if qty_oms != qty_cust:
        issues.append(f"QTY ({int(qty_oms)} vs {int(qty_cust)})")
    if abs(px_oms - px_cust) > PRICE_TOLERANCE:
        issues.append(f"PRICE (${px_oms:.2f} vs ${px_cust:.2f})")
    if dt_oms != dt_cust:
        issues.append(f"SETTLE_DATE ({dt_oms} vs {dt_cust})")

    if not issues:
        return ("MATCHED", "Clean match", "NONE")

    notional_diff = abs((qty_oms * px_oms) - (qty_cust * px_cust))
    if len(issues) > 1 or notional_diff >= 25_000:
        priority = "HIGH"
    elif "QTY" in issues[0] or "PRICE" in issues[0]:
        priority = "MEDIUM"
    else:
        priority = "LOW"

    status = "MULTI_BREAK" if len(issues) > 1 else f"{issues[0].split(' ')[0]}_BREAK"
    return (status, "; ".join(issues), priority)


def run_reconciliation(data_dir: Path, out_file: Path) -> pd.DataFrame:
    """Load OMS, Custodian, and Corporate Action CSVs and produce break report."""
    oms = pd.read_csv(data_dir / "oms_trades.csv")
    cust = pd.read_csv(data_dir / "custodian_trades.csv")
    ca = pd.read_csv(data_dir / "corporate_actions.csv")

    splits = {
        row["ticker"]: float(row["ratio"])
        for _, row in ca.iterrows()
        if str(row["action_type"]).upper() == "SPLIT"
    }

    merged = pd.merge(oms, cust, on="trade_id", how="outer", suffixes=("_oms", "_cust"))
    results = merged.apply(lambda r: classify_break(r, splits), axis=1, result_type="expand")
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
    report.to_csv(out_file, index=False)
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description="Automated Trade Break & Corporate Action Reconciler")
    parser.add_argument("--dir", default=".", help="Directory containing trade CSV files")
    parser.add_argument("--out", default="reconciliation_report.csv", help="Output report CSV")
    args = parser.parse_args()

    data_dir = Path(args.dir)
    if not (data_dir / "oms_trades.csv").exists():
        print("Sample CSVs not found—generating realistic sample blotters...")
        create_sample_data(data_dir)

    report = run_reconciliation(data_dir, data_dir / args.out)
    breaks = report[report["status"] != "MATCHED"]

    print(f"\nReconciled {len(report)} trades | Matched: {len(report) - len(breaks)} | Breaks: {len(breaks)}\n")
    print(report[["trade_id", "account", "ticker", "status", "priority", "details"]].to_string(index=False))
    print(f"\nSaved full report to {args.out}")


if __name__ == "__main__":
    main()