# ASC 606 Revenue Calculator

A FastAPI + vanilla JS web app that automates ASC 606 revenue recognition analysis using a hybrid approach: Python for all deterministic math, Google Gemini AI for judgment-layer reasoning.

---

## Features

- **Five-step ASC 606 analysis** with structured Python-calculated facts and Gemini AI narrative per step
- **Revenue recognition schedule** — monthly revenue, billings, contract asset, and deferred revenue
- **As-of-date snapshot** — recognized-to-date, deferred revenue, and contract asset as of any date
- **SSP allocation** — relative SSP and residual methods
- **Variable consideration** — expected value and most-likely-amount with constraint assessment
- **Contract modifications** — prospective new contract, prospective remaining, and cumulative catch-up
- **Seven realistic example scenarios** covering SaaS, ERP, fintech, ride-hailing, POS hardware, and enterprise banking
- **Build-your-own contract** form for custom scenarios
- **Journal entries** and balance sheet chart per period
- **CSV export** of the full revenue schedule

---

## Architecture

```
main.py                     — FastAPI server (API routes + static file serving)
utils/
  calculation_engine.py     — All deterministic math (no LLM)
  llm_judgments.py          — Gemini API calls for judgment and narrative
static/
  index.html                — Single-page app shell
  app.js                    — All UI logic (vanilla JS)
  app.css                   — Styles
data/examples/              — Seven JSON scenario files (S1–S7)
```

**Python handles:** SSP allocation ratios, VC constraint math, monthly period schedules, cumulative contract asset / liability balances.

**Gemini handles:** SSP estimation when not observable, VC constraint assessment rationale, modification classification, and the 5-step professional narrative with ASC 606 paragraph citations.

---

## Setup

**Requirements:** Python 3.10+  ·  Google Gemini API key (free at [aistudio.google.com](https://aistudio.google.com/app/apikey))

```bash
# 1. Clone
git clone https://github.com/nguyehi1/revenue-analysis.git
cd revenue-analysis

# 2. Create virtual environment and install dependencies
python -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements.txt

# 3. Add your Gemini API key
echo "GEMINI_API_KEY=your-key-here" > .env

# 4. Run
uvicorn main:app --reload
```

The app opens at `http://localhost:8000`.

---

## Example Scenarios

| Scenario | Vendor → Customer | Key Concept |
|---|---|---|
| S1 | CloudHR → Pacific Dental Partners | Simple SaaS, single POB, straight-line over 12 months |
| S2 | Veridian ERP → Hartwell Manufacturing | Multi-POB bundle (ERP + Implementation + Training), SSP allocation |
| S3 | DataStream Analytics → FinEdge Capital | Variable consideration (API overage), expected value + constraint |
| S4 | NexusPlatform → Meridian Retail Group | Contract modification — prospective new contract |
| S5 | PayRoute → SprintPay Technologies | Pure usage-based, 3-tier pricing at Uber/Lyft scale (12M tx/month) |
| S6 | ToastPOS → Bella Cucina Restaurant Group | Hardware (point-in-time) + SaaS + Support bundle, discount allocation |
| S7 | Axiom Cloud → GlobalBank Corp. | Enterprise MSA, 3 Order Forms, volume discount material right |

---

## Usage

1. **Load Example tab** — pick a scenario, review the info card, click **Load & Calculate**
2. The right panel shows:
   - **Recognition Timeline** — stacked bar chart of monthly revenue per POB
   - **Current Position** — as-of-date progress card (deferred revenue, unbilled AR)
   - **Audit Trail** — 5 ASC 606 step accordions with calculated facts + AI reasoning
   - **Outputs** — Balance sheet chart and journal entries, collapsed at the bottom
3. **Build Contract tab** — enter your own contract and click **Calculate Revenue Schedule**
4. Download the full schedule as CSV via **Export CSV**

---

## Project Structure

```
Rev_Analysis/
├── main.py                             # FastAPI application
├── requirements.txt
├── .env                                # API key (not committed)
├── utils/
│   ├── calculation_engine.py           # ASC 606 math engine
│   └── llm_judgments.py               # Gemini AI judgment layer
├── static/
│   ├── index.html
│   ├── app.js
│   └── app.css
└── data/
    └── examples/
        ├── s1_simple_saas.json
        ├── s2_multi_pob_saas_impl_training.json
        ├── s3_variable_consideration.json
        ├── s4_contract_modification.json
        ├── s5_usage_tiers.json
        ├── s6_hardware_software_bundle.json
        └── s7_enterprise_msa_hierarchy.json
```
