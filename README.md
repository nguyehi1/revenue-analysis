# ASC 606 Revenue Recognition Calculator

A Python + Streamlit tool for automated ASC 606 revenue recognition analysis. Combines deterministic Python math for calculations with Google Gemini AI for judgment-layer reasoning across all five ASC 606 steps.

## What It Does

- **Calculates** revenue recognition schedules, SSP-based allocation, variable consideration constraints, and contract asset / deferred revenue balances
- **Reasons** through all five ASC 606 steps using Gemini AI, citing specific paragraph references (ASC 606-10-25-1, -10-32-11, etc.)
- **Handles** common contract complexity: multi-POB bundles, usage-based pricing with tiers, variable consideration, contract modifications, and enterprise MSA hierarchies

## Architecture

| Layer | Responsibility |
|---|---|
| `utils/calculation_engine.py` | All deterministic math: SSP allocation, VC constraint, period schedules, contract asset / liability |
| `utils/llm_judgments.py` | Gemini API calls for judgment: SSP estimation, VC constraint assessment, modification classification, 5-step narrative |
| `app.py` | Streamlit UI: contract input, as-of date snapshot, 5-step reasoning cards |

## Scenarios

Seven example contracts covering the main ASC 606 patterns:

| # | Vendor → Customer | Pattern |
|---|---|---|
| S1 | CloudHR → Pacific Dental Partners | Simple SaaS, single POB, straight-line |
| S2 | Veridian ERP → Hartwell Manufacturing | Multi-POB: SaaS + Implementation + Training, SSP allocation |
| S3 | DataStream Analytics → FinEdge Capital | Variable consideration, expected value method, constraint |
| S4 | NexusPlatform → Meridian Retail Group | Contract modification (prospective new contract) |
| S5 | PayRoute → SprintPay Technologies | Pure usage-based, tiered pricing at Uber/Lyft scale (12M tx/month) |
| S6 | ToastPOS → Bella Cucina Restaurant Group | Hardware + SaaS + Support bundle, point-in-time + over-time |
| S7 | Axiom Cloud → GlobalBank Corp. | Enterprise MSA, 3 Order Forms, volume discount material right |

## Setup

**Requirements:** Python 3.10+, a Google Gemini API key ([get one free](https://aistudio.google.com/app/apikey))

```bash
# 1. Clone and install
git clone https://github.com/nguyehi1/Rev_Analysis.git
cd Rev_Analysis
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

# 2. Add your Gemini API key
cp .env.example .env
# Edit .env and set: GEMINI_API_KEY=your-key-here

# 3. Run
streamlit run app.py
```

## Usage

1. Open the app at `http://localhost:8501`
2. In the **Load Example** tab, select a scenario (S1–S7) and click **Load & Calculate**
3. The right panel shows:
   - **As-of date snapshot**: revenue recognized to date, deferred revenue, contract asset, remaining
   - **5-step ASC 606 cards**: Python-calculated facts + Gemini AI narrative per step
   - **Balance Sheet & Journal Entries**: collapsed section with charts and per-period entries
4. Alternatively, use the **Build Contract** tab to enter a custom contract

## How the Hybrid Model Works

**Python handles all math** — allocation ratios, monthly schedules, running balances — so results are deterministic and auditable.

**Gemini handles judgment** — the things that require professional interpretation:
- Estimating SSP when not directly observable
- Assessing whether variable consideration should be constrained
- Classifying contract modification type
- Writing the 5-step narrative with ASC 606 paragraph citations

The AI reasoning is generated automatically when you click **Load & Calculate**.
