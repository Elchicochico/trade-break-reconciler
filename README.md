Automated Trade Break & Corporate Action Reconciler

A lightweight investment operations reconciliation engine and interactive Streamlit escalation dashboard that compares internal OMS trade blotters against custodian settlement feeds, detects unapplied corporate actions (such as stock splits), and prioritizes breaks by operational risk.

Features

Automated Break Classification:

MISSING_AT_CUSTODIAN / MISSING_AT_OMS

UNAPPLIED_CORP_ACTION (detects quantity/price mismatches explained by stock splits)

PRICE_BREAK (with configurable tolerance)

QTY_BREAK & SETTLE_DATE_BREAK

Escalation Priority Scoring: Ranks breaks from CRITICAL to LOW based on break type and notional dollar exposure.

Interactive Ops Dashboard (reconciler_app.py): Upload custom OMS, Custodian, and Corporate Action CSVs, view match-rate KPIs, filter the escalation queue by priority, and export reconciliation_report.csv.

Self-Contained Sample Data: Automatically generates realistic sample blotters on first run for instant testing.

Quickstart

1. Install dependencies

pip3 install -r requirements.txt


2. Run the interactive Ops dashboard

python3 -m streamlit run reconciler_app.py


3. Or run the CLI reconciler

python3 trade_reconciler.py


This prints the prioritized break summary in the terminal and exports reconciliation_report.csv.

Project Structure

.
├── trade_reconciler.py   # Reconciliation engine, break classifier, & sample data generator
├── reconciler_app.py     # Interactive Streamlit Ops Escalation dashboard
├── requirements.txt      # Python dependencies
└── README.md
