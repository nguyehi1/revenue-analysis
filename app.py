import os
import streamlit as st
import json
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
from pathlib import Path
from datetime import date as date_type, datetime
import logging

# Load .env if present (picks up ANTHROPIC_API_KEY for local dev)
try:
    from dotenv import load_dotenv
    load_dotenv(Path(__file__).parent / ".env", override=True)
except ImportError:
    pass

from utils.calculation_engine import generate_schedule, build_reasoning
from utils.llm_judgments import explain_steps

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

st.set_page_config(
    page_title="ASC 606 Revenue Calculator",
    layout="wide",
    initial_sidebar_state="collapsed",
)


def _load_css(path: Path) -> None:
    try:
        with open(path, "r", encoding="utf-8") as f:
            st.markdown(f"<style>{f.read()}</style>", unsafe_allow_html=True)
    except FileNotFoundError:
        pass


_load_css(Path(__file__).parent / "assets" / "styles.css")


# ---------------------------------------------------------------------------
# Load example contracts from data/examples/
# ---------------------------------------------------------------------------

def _load_examples(examples_dir: Path) -> dict:
    examples = {}
    for path in sorted(examples_dir.glob("s*.json")):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            stem = path.stem
            parts = stem.split("_", 1)
            num = parts[0].upper()
            label = parts[1].replace("_", " ").title() if len(parts) > 1 else stem
            examples[f"{num} — {label}"] = data
        except Exception as e:
            logger.warning("Could not load %s: %s", path.name, e)
    return examples


EXAMPLES = _load_examples(Path(__file__).parent / "data" / "examples")

# Short descriptions shown under each example card
EXAMPLE_DESCRIPTIONS = {
    "S1": "Single POB, fixed price, straight-line. Billed upfront → shows deferred declining to $0.",
    "S2": "Three POBs (SaaS + Implementation + Training). SSP allocation splits $200k. Two billing events.",
    "S3": "SaaS base + usage overage. Variable consideration constrained via expected value.",
    "S4": "24-month SaaS with a mid-term add-on (prospective new contract modification).",
    "S5": "Pure consumption model. Tiered pricing ($0.10 / $0.07 / $0.04). Full VC contract.",
    "S6": "Hardware + SaaS + Support bundle. Discount allocated by SSP ratio. ASC 842 note included.",
    "S7": "Enterprise MSA with 3 Order Forms across 3 years. Volume discount material right.",
}


# ---------------------------------------------------------------------------
# Display helpers
# ---------------------------------------------------------------------------

CHART_HEIGHT = 360
CHART_MARGIN = dict(l=0, r=0, t=36, b=0)
CHART_LEGEND = dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1)

RECOGNITION_TYPES = ["over_time", "point_in_time", "upfront", "usage_based"]
SSP_SOURCES = ["observable", "adjusted_market", "expected_cost_plus_margin", "residual"]


def _fmt(v) -> str:
    try:
        return f"${float(v):,.2f}"
    except Exception:
        return str(v)


def _snapshot(schedule: list, as_of: date_type) -> dict:
    """Return recognized-to-date metrics as of a given date."""
    as_of_str = str(as_of)
    past = [r for r in schedule if r["period_end"] <= as_of_str]
    if past:
        last = past[-1]
        return {
            "rev_to_date": last["cumulative_revenue"],
            "deferred": last["contract_liability"],
            "contract_asset": last["contract_asset"],
            "periods_complete": len(past),
        }
    return {"rev_to_date": 0.0, "deferred": 0.0, "contract_asset": 0.0, "periods_complete": 0}


def _build_display_df(df: pd.DataFrame, obligations: list) -> pd.DataFrame:
    rename = {f"rev_{ob['id']}": ob["name"] for ob in obligations}
    display = df.rename(columns=rename).copy()
    ob_cols = [ob["name"] for ob in obligations]
    cols = (
        ["period", "period_start", "period_end"]
        + [c for c in ob_cols if c in display.columns]
        + [c for c in ["revenue_total", "billings", "contract_asset", "contract_liability"]
           if c in display.columns]
    )
    display = display[[c for c in cols if c in display.columns]]
    for col in display.columns:
        if col not in ("period", "period_start", "period_end"):
            display[col] = display[col].apply(
                lambda x: _fmt(x) if isinstance(x, (int, float)) else x
            )
    return display


def _journal_entries(row: dict, obligations: list) -> list:
    entries = []
    revenue = row.get("revenue_total", 0)
    billings = row.get("billings", 0)

    if billings > 0:
        entries += [
            {"Account": "Accounts Receivable",                   "Debit": _fmt(billings), "Credit": ""},
            {"Account": "Contract Liability (Deferred Revenue)",  "Debit": "",             "Credit": _fmt(billings)},
        ]

    if revenue > 0:
        if len(obligations) > 1:
            for ob in obligations:
                ob_rev = row.get(f"rev_{ob['id']}", 0)
                if ob_rev > 0:
                    entries += [
                        {"Account": f"Contract Liability — {ob['name']}", "Debit": _fmt(ob_rev), "Credit": ""},
                        {"Account": f"Revenue — {ob['name']}",            "Debit": "",           "Credit": _fmt(ob_rev)},
                    ]
        else:
            name = obligations[0]["name"] if obligations else "Revenue"
            entries += [
                {"Account": "Contract Liability (Deferred Revenue)", "Debit": _fmt(revenue), "Credit": ""},
                {"Account": f"Revenue — {name}",                     "Debit": "",            "Credit": _fmt(revenue)},
            ]
    return entries


def _run_calculation(contract: dict) -> None:
    """Run the engine, generate AI reasoning, and store everything in session state."""
    result = generate_schedule(contract)
    st.session_state.result   = result
    st.session_state.contract = contract
    step_data = build_reasoning(contract, result)
    try:
        st.session_state.ai_reasoning = explain_steps(contract, step_data)
    except Exception as e:
        logger.error("AI reasoning failed during calculation: %s", e)
        st.session_state.ai_reasoning = {}


# ---------------------------------------------------------------------------
# Page header
# ---------------------------------------------------------------------------

st.markdown(
    '<div class="topbar"><div class="brand">ASC 606 Revenue Recognition Calculator</div></div>',
    unsafe_allow_html=True,
)

col_left, col_right = st.columns([4, 6], gap="medium")

# ===========================================================================
# LEFT COLUMN — two tabs: Load Example | Build Contract
# ===========================================================================
with col_left:
    st.markdown("### Contract Input")
    tab_ex, tab_build = st.tabs(["Load Example", "Build Contract"])

    # -----------------------------------------------------------------------
    # Tab 1: Load Example
    # -----------------------------------------------------------------------
    with tab_ex:
        selected = st.selectbox(
            "Select scenario",
            list(EXAMPLES.keys()),
            label_visibility="visible",
        )

        if selected:
            data = EXAMPLES[selected]
            num_key = selected.split("—")[0].strip()  # e.g. "S1"
            desc = EXAMPLE_DESCRIPTIONS.get(num_key, "")

            # Info card
            n_pobs = len(data.get("performance_obligations", data.get("order_forms", [{}])[0].get("performance_obligations", [])))
            start = data.get("start_date", "—")
            end   = data.get("end_date", "—")
            tcv   = data.get("total_contract_value", 0)

            st.markdown(
                f"""
                <div style="background:#f8f9fa;border-radius:8px;padding:12px 16px;margin-bottom:12px;border:1px solid #e0e0e0">
                  <div style="font-size:13px;color:#555;margin-bottom:4px">{desc}</div>
                  <div style="font-size:12px;color:#888">{start} → {end} &nbsp;|&nbsp; TCV {_fmt(tcv)} &nbsp;|&nbsp; {n_pobs} POB(s)</div>
                </div>
                """,
                unsafe_allow_html=True,
            )

            if st.button("Load & Calculate", type="primary", use_container_width=True, key="btn_ex"):
                with st.spinner("Calculating and generating reasoning…"):
                    try:
                        _run_calculation(data)
                    except Exception as e:
                        st.error(f"Calculation error — {e}")
                        logger.exception("Example calculation failed")

    # -----------------------------------------------------------------------
    # Tab 2: Build Contract
    # -----------------------------------------------------------------------
    with tab_build:
        # -- Session state init --
        for key, default in [("n_pobs", 1), ("n_pays", 1)]:
            if key not in st.session_state:
                st.session_state[key] = default

        # -- Contract basics --
        col_a, col_b = st.columns(2)
        b_id  = col_a.text_input("Contract ID", value="C-NEW", key="b_id")
        b_cur = col_b.selectbox("Currency", ["USD", "EUR", "GBP", "CAD"], key="b_cur")

        col_c, col_d = st.columns(2)
        b_start = col_c.date_input("Start Date", value=date_type(2024, 1, 1), key="b_start")
        b_end   = col_d.date_input("End Date",   value=date_type(2024, 12, 31), key="b_end")

        b_tcv = st.number_input(
            "Total Contract Value ($)", min_value=0.0, value=0.0,
            step=1000.0, format="%.2f", key="b_tcv",
        )

        st.divider()

        # -- Performance obligations --
        st.markdown("**Performance Obligations**")
        for i in range(st.session_state.n_pobs):
            with st.expander(f"POB {i + 1}", expanded=True):
                p_name = st.text_input("Name", key=f"p_name_{i}",
                                       placeholder="e.g. SaaS Platform Access")
                c1, c2 = st.columns(2)
                p_rec  = c1.selectbox("Recognition type", RECOGNITION_TYPES,
                                      key=f"p_rec_{i}")
                p_ssp  = c2.number_input("SSP ($)", min_value=0.0, step=1000.0,
                                         format="%.2f", key=f"p_ssp_{i}",
                                         help="Standalone selling price. Leave 0 for residual.")
                p_src  = st.selectbox("SSP source", SSP_SOURCES, key=f"p_src_{i}")
                p_date = None
                if p_rec == "point_in_time":
                    p_date = st.date_input("Completion date", key=f"p_date_{i}",
                                           value=b_end)

        c_add, c_rem = st.columns(2)
        if c_add.button("＋ Add POB", key="add_pob", use_container_width=True):
            st.session_state.n_pobs += 1
            st.rerun()
        if c_rem.button("－ Remove POB", key="rem_pob", use_container_width=True,
                        disabled=st.session_state.n_pobs <= 1):
            st.session_state.n_pobs -= 1
            st.rerun()

        st.divider()

        # -- Payment schedule --
        st.markdown("**Payment Schedule**")
        for i in range(st.session_state.n_pays):
            c1, c2 = st.columns(2)
            c1.date_input("Invoice date", value=b_start, key=f"pay_dt_{i}")
            c2.number_input("Amount ($)", min_value=0.0, step=1000.0,
                            format="%.2f", key=f"pay_amt_{i}")

        c_add2, c_rem2 = st.columns(2)
        if c_add2.button("＋ Add Payment", key="add_pay", use_container_width=True):
            st.session_state.n_pays += 1
            st.rerun()
        if c_rem2.button("－ Remove Payment", key="rem_pay", use_container_width=True,
                         disabled=st.session_state.n_pays <= 1):
            st.session_state.n_pays -= 1
            st.rerun()

        st.divider()

        if st.button("Calculate Revenue Schedule", type="primary",
                     use_container_width=True, key="btn_build"):
            errors = []
            if b_start >= b_end:
                errors.append("End date must be after start date.")
            if b_tcv <= 0:
                errors.append("Total contract value must be greater than 0.")

            pob_list = []
            for i in range(st.session_state.n_pobs):
                name = st.session_state.get(f"p_name_{i}", "").strip()
                if not name:
                    errors.append(f"POB {i + 1} is missing a name.")
                    continue
                rec  = st.session_state.get(f"p_rec_{i}", "over_time")
                ssp  = float(st.session_state.get(f"p_ssp_{i}", 0))
                src  = st.session_state.get(f"p_src_{i}", "observable")
                pdate = st.session_state.get(f"p_date_{i}")

                ob = {
                    "id": f"POB-{i + 1}",
                    "name": name,
                    "recognition_type": rec,
                    "recognition_params": {},
                    "ssp": {"amount": ssp if ssp > 0 else None, "source": src},
                }
                if rec == "point_in_time" and pdate:
                    ob["recognition_params"]["estimated_completion_date"] = str(pdate)
                pob_list.append(ob)

            pay_list = []
            for i in range(st.session_state.n_pays):
                amt  = float(st.session_state.get(f"pay_amt_{i}", 0))
                pdt  = st.session_state.get(f"pay_dt_{i}", b_start)
                if amt > 0:
                    pay_list.append({"invoice_date": str(pdt), "amount": amt})

            if errors:
                for e in errors:
                    st.error(e)
            else:
                contract = {
                    "contract_id": b_id,
                    "start_date": str(b_start),
                    "end_date": str(b_end),
                    "currency": b_cur,
                    "total_contract_value": b_tcv,
                    "performance_obligations": pob_list,
                    "payment_schedule": pay_list,
                }
                with st.spinner("Calculating and generating reasoning…"):
                    try:
                        _run_calculation(contract)
                    except Exception as e:
                        st.error(f"Calculation error — {e}")
                        logger.exception("Build calculation failed")


# ===========================================================================
# RIGHT COLUMN — 5-step reasoning + as-of snapshot
# ===========================================================================

STEP_TITLES = {
    "step_1": "Step 1 — Identify the Contract",
    "step_2": "Step 2 — Identify Performance Obligations",
    "step_3": "Step 3 — Determine Transaction Price",
    "step_4": "Step 4 — Allocate Transaction Price",
    "step_5": "Step 5 — Recognize Revenue",
}

SSP_SOURCE_LABELS = {
    "observable":               "Observable (direct evidence)",
    "adjusted_market":          "Adjusted market assessment",
    "expected_cost_plus_margin":"Expected cost + margin",
    "residual":                 "Residual method",
}

REC_TYPE_LABELS = {
    "over_time":    "Over time",
    "point_in_time":"Point-in-time",
    "upfront":      "Upfront (point-in-time, day 1)",
    "usage_based":  "Usage-based",
}


def _ai_badge(text: str) -> None:
    st.markdown(
        f'<div style="background:#f0f4ff;border-left:3px solid #4a7cdc;'
        f'border-radius:4px;padding:10px 14px;margin-top:8px;font-size:13px;'
        f'color:#333;line-height:1.6">{text}</div>',
        unsafe_allow_html=True,
    )


_api_key_missing = not os.environ.get("GEMINI_API_KEY")

with col_right:
    if _api_key_missing:
        st.warning(
            "**GEMINI_API_KEY not set** — AI reasoning will be unavailable. "
            "Copy `.env.example` to `.env`, add your key, and restart the app.",
            icon="⚠",
        )

    if "result" not in st.session_state:
        st.info(
            "Select an example from **Load Example** or fill in **Build Contract**, "
            "then click **Calculate**."
        )
    else:
        result      = st.session_state.result
        contract    = st.session_state.contract
        schedule    = result["schedule"]
        obligations = result["obligations"]
        summary     = result["summary"]
        df          = pd.DataFrame(schedule)
        step_data   = build_reasoning(contract, result)

        # ------------------------------------------------------------------
        # As-of date + snapshot metrics
        # ------------------------------------------------------------------
        col_ao, col_spacer = st.columns([2, 3])
        as_of = col_ao.date_input(
            "As of date",
            value=date_type.today(),
            help="Snapshot of recognized revenue and balance as of this date.",
            key="as_of_date",
        )

        snap      = _snapshot(schedule, as_of)
        remaining = max(0.0, summary["total_contract_value"] - snap["rev_to_date"])

        m1, m2, m3, m4 = st.columns(4)
        m1.metric(
            "Recognized to Date", _fmt(snap["rev_to_date"]),
            help=f"{snap['periods_complete']} of {summary['duration_months']} periods complete",
        )
        m2.metric("Deferred Revenue",      _fmt(snap["deferred"]))
        m3.metric("Contract Asset",        _fmt(snap["contract_asset"]),
                  help="Unbilled AR — revenue exceeds billings")
        m4.metric("Remaining to Recognize", _fmt(remaining))

        st.caption(
            f"**{summary['contract_id']}** &nbsp;|&nbsp; "
            f"TCV {_fmt(summary['total_contract_value'])} &nbsp;|&nbsp; "
            f"{summary['duration_months']} months &nbsp;|&nbsp; "
            f"{summary['num_obligations']} obligation(s)"
        )

        st.divider()

        # ------------------------------------------------------------------
        # AI reasoning status
        # ------------------------------------------------------------------
        ai_reasoning = st.session_state.get("ai_reasoning", {})

        st.divider()

        # ------------------------------------------------------------------
        # Step 1 — Identify the Contract
        # ------------------------------------------------------------------
        with st.expander(STEP_TITLES["step_1"], expanded=True):
            s1 = step_data["step_1"]
            c1, c2, c3 = st.columns(3)
            c1.metric("Contract ID",  s1["contract_id"])
            c2.metric("TCV",          _fmt(s1["total_contract_value"]))
            c3.metric("Duration",     f"{s1['duration_months']} months")

            c4, c5, c6 = st.columns(3)
            c4.metric("Start",        s1["start_date"])
            c5.metric("End",          s1["end_date"])
            c6.metric("Modifications","Yes" if s1["has_modifications"] else "No")

            if ai_reasoning.get("step_1"):
                _ai_badge(ai_reasoning["step_1"])

        # ------------------------------------------------------------------
        # Step 2 — Identify Performance Obligations
        # ------------------------------------------------------------------
        with st.expander(STEP_TITLES["step_2"], expanded=True):
            s2 = step_data["step_2"]
            rows = []
            for ob in s2["obligations"]:
                rows.append({
                    "POB":              ob["name"],
                    "Recognition":      REC_TYPE_LABELS.get(ob["recognition_type"], ob["recognition_type"]),
                    "SSP Source":       SSP_SOURCE_LABELS.get(ob["ssp_source"], ob["ssp_source"]),
                    "SSP ($)":          _fmt(ob["ssp_amount"]) if ob["ssp_amount"] else "Residual",
                    "Modification POB": "Yes" if ob["is_modification"] else "—",
                })
            st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)

            if ai_reasoning.get("step_2"):
                _ai_badge(ai_reasoning["step_2"])

        # ------------------------------------------------------------------
        # Step 3 — Determine Transaction Price
        # ------------------------------------------------------------------
        with st.expander(STEP_TITLES["step_3"], expanded=True):
            s3 = step_data["step_3"]
            c1, c2 = st.columns(2)
            c1.metric("Fixed Consideration",   _fmt(s3["fixed_consideration"]))
            c2.metric("Transaction Price",     _fmt(s3["transaction_price"]))

            if s3["variable_consideration"]:
                vc = s3["variable_consideration"]
                st.markdown("**Variable Consideration**")
                vc_cols = st.columns(3)
                vc_cols[0].metric("POB",    vc["pob_id"])
                vc_cols[1].metric("Method", vc["method"].replace("_", " ").title())
                vc_cols[2].metric("Constrained Amount", _fmt(vc["constrained_amount"]))

                if vc.get("scenarios"):
                    sc_df = pd.DataFrame(vc["scenarios"])
                    sc_df.columns = [c.replace("_", " ").title() for c in sc_df.columns]
                    st.dataframe(sc_df, use_container_width=True, hide_index=True)
            else:
                st.caption("No variable consideration.")

            if s3["significant_financing_component"]:
                st.warning(
                    f"Significant financing component may exist — "
                    f"max payment gap is {s3['max_payment_gap_months']:.0f} months "
                    f"(> 12-month practical expedient under ASC 606-10-32-18)."
                )
            else:
                st.caption(
                    f"No significant financing component "
                    f"(max payment gap: {s3['max_payment_gap_months']:.0f} months)."
                )

            if ai_reasoning.get("step_3"):
                _ai_badge(ai_reasoning["step_3"])

        # ------------------------------------------------------------------
        # Step 4 — Allocate Transaction Price
        # ------------------------------------------------------------------
        with st.expander(STEP_TITLES["step_4"], expanded=True):
            s4 = step_data["step_4"]
            method_label = "Relative SSP" if s4["method"] == "relative_ssp" else "Residual Method"
            c1, c2, c3 = st.columns(3)
            c1.metric("Allocation Method", method_label)
            c2.metric("Total SSP",         _fmt(s4["total_ssp"]) if s4["total_ssp"] else "N/A")
            c3.metric("Discount",          _fmt(s4["discount"]) if s4["discount"] else "$0.00")

            alloc_rows = []
            for a in s4["allocations"]:
                alloc_rows.append({
                    "POB":           a["name"],
                    "SSP ($)":       _fmt(a["ssp"]) if a["ssp"] else "Residual",
                    "SSP Source":    SSP_SOURCE_LABELS.get(a["ssp_source"], a["ssp_source"] or "—"),
                    "SSP %":         f"{a['ssp_pct']:.1f}%" if a["ssp_pct"] else "—",
                    "Allocated ($)": _fmt(a["allocated_value"]),
                })
            # Totals row
            total_alloc = sum(a["allocated_value"] for a in s4["allocations"])
            alloc_rows.append({
                "POB": "**Total**", "SSP ($)": "", "SSP Source": "",
                "SSP %": "100.0%" if s4["method"] == "relative_ssp" else "—",
                "Allocated ($)": _fmt(total_alloc),
            })
            st.dataframe(pd.DataFrame(alloc_rows), use_container_width=True, hide_index=True)

            if ai_reasoning.get("step_4"):
                _ai_badge(ai_reasoning["step_4"])

        # ------------------------------------------------------------------
        # Step 5 — Recognize Revenue
        # ------------------------------------------------------------------
        with st.expander(STEP_TITLES["step_5"], expanded=True):
            s5 = step_data["step_5"]

            rec_rows = []
            for r in s5["recognition_summary"]:
                if r["pattern"] == "over_time":
                    schedule_desc = f"{_fmt(r['monthly_amount'])}/month × {r['periods']} months"
                elif r["pattern"] in ("point_in_time", "upfront"):
                    date_str = r.get("completion_date") or "Day 1"
                    schedule_desc = f"{_fmt(r['amount'])} on {date_str}"
                else:
                    schedule_desc = f"~{_fmt(r['estimated_monthly'])}/month (usage estimate)"
                rec_rows.append({
                    "POB":       r["name"],
                    "Pattern":   REC_TYPE_LABELS.get(r["pattern"], r["pattern"]),
                    "Schedule":  schedule_desc,
                    "Total ($)": _fmt(r.get("total") or r.get("amount") or r.get("total_constrained", 0)),
                })
            st.dataframe(pd.DataFrame(rec_rows), use_container_width=True, hide_index=True)

            # Revenue chart
            ob_cols  = [ob["name"] for ob in obligations]
            rev_cols = [f"rev_{ob['id']}" for ob in obligations]
            plot_df  = df[["period"] + rev_cols].copy()
            plot_df.columns = ["period"] + ob_cols

            fig = px.bar(
                plot_df, x="period", y=ob_cols,
                title="Revenue Recognition Schedule",
                labels={"value": "Revenue ($)", "variable": "Obligation"},
            )
            fig.update_layout(
                barmode="stack", height=CHART_HEIGHT,
                margin=CHART_MARGIN, legend=CHART_LEGEND,
            )

            # Mark as-of date on the chart
            as_of_str = str(as_of)
            past_periods = df.loc[df["period_end"] <= as_of_str, "period"]
            if not past_periods.empty:
                _x = past_periods.iloc[-1]
                fig.add_shape(type="line", xref="x", yref="paper",
                              x0=_x, x1=_x, y0=0, y1=1,
                              line=dict(dash="dash", color="#888"))
                fig.add_annotation(xref="x", yref="paper", x=_x, y=0.97,
                                   text="As of date", showarrow=False,
                                   xanchor="right", font=dict(color="#888", size=11))
            st.plotly_chart(fig, use_container_width=True)

            if ai_reasoning.get("step_5"):
                _ai_badge(ai_reasoning["step_5"])

        # ------------------------------------------------------------------
        # Collapsed: Balance sheet + Journal entries
        # ------------------------------------------------------------------
        with st.expander("Balance Sheet & Journal Entries", expanded=False):
            bal_tab, je_tab = st.tabs(["Balance Sheet", "Journal Entries"])

            with bal_tab:
                fig_b = go.Figure()
                fig_b.add_trace(go.Scatter(
                    x=df["period"], y=df["contract_liability"],
                    mode="lines+markers", name="Contract Liability (Deferred Revenue)",
                    fill="tozeroy", line=dict(color="#FF6B6B", width=2), marker=dict(size=5),
                ))
                fig_b.add_trace(go.Scatter(
                    x=df["period"], y=df["contract_asset"],
                    mode="lines+markers", name="Contract Asset (Unbilled AR)",
                    fill="tozeroy", line=dict(color="#4ECDC4", width=2), marker=dict(size=5),
                ))
                if not past_periods.empty:
                    _xb = past_periods.iloc[-1]
                    fig_b.add_shape(type="line", xref="x", yref="paper",
                                    x0=_xb, x1=_xb, y0=0, y1=1,
                                    line=dict(dash="dash", color="#888"))
                    fig_b.add_annotation(xref="x", yref="paper", x=_xb, y=0.97,
                                         text="As of date", showarrow=False,
                                         xanchor="right", font=dict(color="#888", size=11))
                fig_b.update_layout(
                    title="Contract Asset vs. Contract Liability",
                    xaxis_title="Period", yaxis_title="Balance ($)",
                    height=CHART_HEIGHT, margin=CHART_MARGIN, legend=CHART_LEGEND,
                    hovermode="x unified",
                )
                st.plotly_chart(fig_b, use_container_width=True)
                st.caption(
                    "**Contract Liability** = billings exceed revenue (deferred revenue). "
                    "**Contract Asset** = revenue exceeds billings (unbilled AR)."
                )

                st.download_button(
                    "Download Revenue Schedule CSV",
                    data=df.to_csv(index=False).encode("utf-8"),
                    file_name=f"{summary['contract_id']}_schedule.csv",
                    mime="text/csv",
                )

            with je_tab:
                st.caption("Revenue recognition and billing entries per period.")
                for row in schedule:
                    revenue  = row.get("revenue_total", 0)
                    billings = row.get("billings", 0)
                    if revenue == 0 and billings == 0:
                        continue
                    label = f"{row['period']}  —  Revenue {_fmt(revenue)}"
                    if billings > 0:
                        label += f"  |  Billed {_fmt(billings)}"
                    with st.expander(label, expanded=False):
                        entries = _journal_entries(row, obligations)
                        if entries:
                            st.dataframe(pd.DataFrame(entries), use_container_width=True,
                                         hide_index=True)
                        else:
                            st.caption("No entries for this period.")

st.markdown("---")
st.caption("ASC 606 Revenue Recognition Calculator")
