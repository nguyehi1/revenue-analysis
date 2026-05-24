from typing import List, Dict, Any, Tuple, Optional
from datetime import datetime, timedelta
from dateutil.relativedelta import relativedelta
import logging

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Date helpers
# ---------------------------------------------------------------------------

def _parse_date(date_str: str) -> datetime:
    return datetime.strptime(date_str, "%Y-%m-%d")


def _duration_months(start: datetime, end: datetime) -> int:
    n = (end.year - start.year) * 12 + (end.month - start.month)
    if end.day >= start.day:
        n += 1
    return max(1, n)


def _period_end(month_start: datetime, contract_end: datetime) -> datetime:
    return min(month_start + relativedelta(months=1) - timedelta(days=1), contract_end)


def _months_range(start: datetime, end: datetime) -> List[datetime]:
    n = _duration_months(start, end)
    return [start + relativedelta(months=i) for i in range(n)]


# ---------------------------------------------------------------------------
# Step 1 — SSP-based allocation
# ---------------------------------------------------------------------------

def allocate_by_ssp(obligations: List[Dict], tcv: float) -> List[Dict]:
    """
    Allocate TCV across obligations using standalone selling prices.

    Relative SSP method  — all SSPs provided → allocate proportionally.
    Residual method      — one SSP is null or source='residual' → that POB
                           gets TCV minus the sum of all known SSPs.
    """
    result = [ob.copy() for ob in obligations]

    known_idx = [
        i for i, ob in enumerate(result)
        if ob.get("ssp", {}).get("source") != "residual"
        and ob.get("ssp", {}).get("amount") is not None
    ]
    residual_idx = [i for i in range(len(result)) if i not in known_idx]

    total_known_ssp = sum(float(result[i]["ssp"]["amount"]) for i in known_idx)

    if not residual_idx:
        # Relative SSP: allocate proportionally to TCV
        for i in known_idx:
            ssp = float(result[i]["ssp"]["amount"])
            result[i]["allocated_value"] = round(tcv * ssp / total_known_ssp, 2)
    else:
        # Residual: known obs get their SSP as allocated value
        for i in known_idx:
            result[i]["allocated_value"] = float(result[i]["ssp"]["amount"])
        residual_total = round(tcv - total_known_ssp, 2)
        per_residual = round(residual_total / len(residual_idx), 2) if residual_idx else 0.0
        for i in residual_idx:
            result[i]["allocated_value"] = per_residual

    return result


# ---------------------------------------------------------------------------
# Step 2 — Variable consideration
# ---------------------------------------------------------------------------

def apply_variable_consideration(
    obligations: List[Dict], vc: Dict
) -> Tuple[List[Dict], float]:
    """
    Apply variable consideration to the target POB.

    If constrained_amount is provided it is used directly (e.g. set by LLM
    judgment).  Otherwise the unconstrained expected value is computed from
    the scenarios and used as the constrained amount.

    Returns updated obligations and the VC amount added.
    """
    pob_id = vc.get("pob_id")
    method = vc.get("estimation_method", "expected_value")
    constrained = vc.get("constrained_amount")

    if constrained is None:
        scenarios = vc.get("scenarios", [])
        if method == "expected_value":
            constrained = sum(
                float(s["annual_amount"]) * float(s["probability"])
                for s in scenarios
            )
        else:  # most_likely
            constrained = max(scenarios, key=lambda s: s["probability"])["annual_amount"]
        constrained = round(constrained, 2)

    result = [ob.copy() for ob in obligations]
    for ob in result:
        if ob["id"] == pob_id:
            ob["allocated_value"] = float(ob.get("allocated_value", 0)) + constrained
            break

    return result, constrained


# ---------------------------------------------------------------------------
# Step 3 — Per-obligation revenue schedule
# ---------------------------------------------------------------------------

def _ob_revenue_by_period(
    ob: Dict,
    months: List[datetime],
    contract_end: datetime,
) -> Dict[str, float]:
    """Return {period: revenue_amount} for one obligation."""
    allocated = float(ob.get("allocated_value", 0))
    recognition = ob.get("recognition_type", "over_time").lower()
    params = ob.get("recognition_params", {})
    n = len(months)
    schedule: Dict[str, float] = {m.strftime("%Y-%m"): 0.0 for m in months}

    if recognition in ("point_in_time", "upfront"):
        date_str = params.get("estimated_completion_date")
        if date_str and recognition == "point_in_time":
            event_date = _parse_date(date_str)
            for m in months:
                if m <= event_date <= _period_end(m, contract_end):
                    schedule[m.strftime("%Y-%m")] = round(allocated, 2)
                    break
            else:
                # Event outside contract range → first period
                if months:
                    schedule[months[0].strftime("%Y-%m")] = round(allocated, 2)
        else:
            if months:
                schedule[months[0].strftime("%Y-%m")] = round(allocated, 2)
    else:
        # over_time, usage_based, and unknown types: spread evenly (straight-line)
        if recognition not in ("over_time", "usage_based"):
            logger.warning("Unknown recognition_type '%s' — defaulting to straight-line", recognition)
        monthly   = round(allocated / n, 2)
        remainder = round(allocated - monthly * (n - 1), 2)
        for idx, m in enumerate(months):
            schedule[m.strftime("%Y-%m")] = remainder if idx == n - 1 else monthly

    return schedule


# ---------------------------------------------------------------------------
# Step 4 — Billing schedule
# ---------------------------------------------------------------------------

def _billing_by_period(
    payment_schedule: List[Dict],
    months: List[datetime],
    start_date: datetime,
    contract_end: datetime,
) -> Dict[str, float]:
    """Map invoice amounts to the period in which they are billed."""
    result: Dict[str, float] = {m.strftime("%Y-%m"): 0.0 for m in months}

    for payment in payment_schedule:
        raw_amount = payment.get("amount", 0)
        amount = float(
            payment.get("estimated", raw_amount)
            if raw_amount == "variable"
            else raw_amount
        )

        date_str = payment.get("invoice_date")
        if not date_str:
            continue
        invoice_date = _parse_date(date_str)

        placed = False
        for m in months:
            if m <= invoice_date <= _period_end(m, contract_end):
                result[m.strftime("%Y-%m")] += amount
                placed = True
                break

        if not placed and invoice_date < start_date and months:
            result[months[0].strftime("%Y-%m")] += amount

    return result


# ---------------------------------------------------------------------------
# Main orchestrator
# ---------------------------------------------------------------------------

def generate_schedule(contract: Dict[str, Any]) -> Dict[str, Any]:
    """
    Generate a full ASC 606 revenue recognition schedule from a contract JSON.

    Handles:
      - Single and multi-obligation contracts
      - SSP-based allocation (relative and residual methods)
      - Variable consideration with constraint
      - Payment schedule → contract asset / contract liability per period
      - Prospective contract modifications (distinct new POBs at SSP)

    Returns a dict with keys:
      schedule     — list of period records
      obligations  — list of obligations with allocated_value filled in
      summary      — contract-level totals
    """
    start_date = _parse_date(contract["start_date"])
    end_date = _parse_date(contract["end_date"])
    tcv = float(contract["total_contract_value"])
    obligations = [ob.copy() for ob in contract.get("performance_obligations", [])]
    payment_schedule = list(contract.get("payment_schedule", []))
    vc = contract.get("variable_consideration")
    modifications = contract.get("modifications", [])

    months = _months_range(start_date, end_date)

    # --- Collect modification POBs (prospective new-contract treatment) ---
    mod_obs: List[Dict] = []
    for mod in modifications:
        for new_ob in mod.get("new_performance_obligations", []):
            ob = new_ob.copy()
            ob["_mod_start"] = _parse_date(ob.get("start_date", contract["start_date"]))
            ob["_mod_end"] = _parse_date(ob.get("end_date", contract["end_date"]))
            # Prospective: allocated value = SSP of the new POB
            ob["allocated_value"] = float(ob.get("ssp", {}).get("amount") or 0)
            mod_obs.append(ob)
        payment_schedule.extend(mod.get("additional_payment", []))

    # --- Step 1: Allocate base TCV ---
    if len(obligations) > 1:
        obligations = allocate_by_ssp(obligations, tcv)
    elif len(obligations) == 1:
        obligations[0]["allocated_value"] = tcv

    # --- Step 2: Variable consideration ---
    vc_amount = 0.0
    if vc:
        obligations, vc_amount = apply_variable_consideration(obligations, vc)

    # --- Step 3: Revenue by period per obligation ---
    ob_schedules: Dict[str, Dict[str, float]] = {}

    for ob in obligations:
        ob_schedules[ob["id"]] = _ob_revenue_by_period(ob, months, end_date)

    for mod_ob in mod_obs:
        mod_months = _months_range(mod_ob["_mod_start"], mod_ob["_mod_end"])
        ob_schedules[mod_ob["id"]] = _ob_revenue_by_period(
            mod_ob, mod_months, mod_ob["_mod_end"]
        )

    # --- Step 4: Billings by period ---
    billings = _billing_by_period(payment_schedule, months, start_date, end_date)

    # --- Step 5: Build period records ---
    all_obligations = obligations + mod_obs
    schedule = []
    cum_rev = 0.0
    cum_bil = 0.0

    for month_start in months:
        period = month_start.strftime("%Y-%m")
        pe = _period_end(month_start, end_date)

        record: Dict[str, Any] = {
            "period": period,
            "period_start": month_start.strftime("%Y-%m-%d"),
            "period_end": pe.strftime("%Y-%m-%d"),
        }

        period_rev = 0.0
        for ob in all_obligations:
            rev = ob_schedules.get(ob["id"], {}).get(period, 0.0)
            record[f"rev_{ob['id']}"] = round(rev, 2)
            period_rev += rev

        period_bil = billings.get(period, 0.0)
        record["revenue_total"] = round(period_rev, 2)
        record["billings"] = round(period_bil, 2)

        cum_rev += period_rev
        cum_bil += period_bil
        record["cumulative_revenue"] = round(cum_rev, 2)
        record["cumulative_billings"] = round(cum_bil, 2)

        net = cum_rev - cum_bil
        record["contract_asset"] = round(max(0.0, net), 2)       # unbilled AR
        record["contract_liability"] = round(max(0.0, -net), 2)  # deferred revenue

        schedule.append(record)

    return {
        "schedule": schedule,
        "obligations": all_obligations,
        "summary": {
            "contract_id": contract.get("contract_id", "N/A"),
            "total_contract_value": tcv,
            "variable_consideration_included": vc_amount,
            "duration_months": len(months),
            "num_obligations": len(all_obligations),
        },
    }


# ---------------------------------------------------------------------------
# 5-Step reasoning data builder
# ---------------------------------------------------------------------------

def build_reasoning(contract: Dict[str, Any], result: Dict[str, Any]) -> Dict[str, Any]:
    """
    Extract structured facts for each of the 5 ASC 606 steps.
    Output feeds both the UI cards and the LLM narrative prompt.
    """
    obligations = result["obligations"]
    summary     = result["summary"]
    tcv         = float(contract["total_contract_value"])
    vc_contract = contract.get("variable_consideration")
    payments    = contract.get("payment_schedule", [])

    # ------------------------------------------------------------------
    # Step 1 — Identify the Contract
    # ------------------------------------------------------------------
    step1 = {
        "contract_id":    contract.get("contract_id", "N/A"),
        "start_date":     contract.get("start_date"),
        "end_date":       contract.get("end_date"),
        "duration_months": summary["duration_months"],
        "total_contract_value": tcv,
        "currency":       contract.get("currency", "USD"),
        "num_obligations": summary["num_obligations"],
        "has_modifications": bool(contract.get("modifications")),
    }

    # ------------------------------------------------------------------
    # Step 2 — Identify Performance Obligations
    # ------------------------------------------------------------------
    step2 = {
        "obligations": [
            {
                "id":               ob["id"],
                "name":             ob["name"],
                "description":      ob.get("description", ""),
                "recognition_type": ob.get("recognition_type", "over_time"),
                "ssp_source":       ob.get("ssp", {}).get("source", "observable"),
                "ssp_amount":       ob.get("ssp", {}).get("amount"),
                "is_modification":  "_mod_start" in ob,
            }
            for ob in obligations
        ]
    }

    # ------------------------------------------------------------------
    # Step 3 — Determine Transaction Price
    # ------------------------------------------------------------------
    vc_included = summary.get("variable_consideration_included") or 0.0
    vc_data = None
    if vc_contract:
        vc_data = {
            "pob_id":           vc_contract.get("pob_id"),
            "method":           vc_contract.get("estimation_method"),
            "constrained_amount": vc_included,
            "scenarios":        vc_contract.get("scenarios", []),
        }

    # Significant financing: any payment more than 12 months from contract start
    start_dt = _parse_date(contract["start_date"])
    max_gap  = 0
    for pay in payments:
        raw = pay.get("invoice_date")
        if raw:
            gap = abs(((_parse_date(raw) - start_dt).days) / 30.44)
            max_gap = max(max_gap, gap)

    step3 = {
        "fixed_consideration":           round(tcv - vc_included, 2),
        "variable_consideration":        vc_data,
        "transaction_price":             tcv,
        "significant_financing_component": max_gap > 12,
        "max_payment_gap_months":        round(max_gap, 1),
    }

    # ------------------------------------------------------------------
    # Step 4 — Allocate Transaction Price
    # ------------------------------------------------------------------
    has_residual = any(
        ob.get("ssp", {}).get("source") == "residual"
        or ob.get("ssp", {}).get("amount") is None
        for ob in obligations
    )
    method = "residual" if has_residual else "relative_ssp"

    known_ssps = [
        float(ob["ssp"]["amount"])
        for ob in obligations
        if ob.get("ssp", {}).get("source") != "residual"
        and ob.get("ssp", {}).get("amount") is not None
    ]
    total_ssp = sum(known_ssps)

    allocations = []
    for ob in obligations:
        ssp = ob.get("ssp", {}).get("amount")
        ssp_f = float(ssp) if ssp is not None else None
        allocated = float(ob.get("allocated_value", 0))
        ssp_pct = round(ssp_f / total_ssp * 100, 1) if (ssp_f and total_ssp > 0) else None
        allocations.append({
            "id":              ob["id"],
            "name":            ob["name"],
            "ssp":             ssp_f,
            "ssp_source":      ob.get("ssp", {}).get("source"),
            "ssp_pct":         ssp_pct,
            "allocated_value": allocated,
        })

    discount = round(total_ssp - tcv, 2) if (method == "relative_ssp" and total_ssp > 0) else 0.0

    step4 = {
        "method":      method,
        "total_ssp":   total_ssp,
        "discount":    discount,
        "allocations": allocations,
    }

    # ------------------------------------------------------------------
    # Step 5 — Recognize Revenue
    # ------------------------------------------------------------------
    recognition_summary = []
    for ob in obligations:
        rec   = ob.get("recognition_type", "over_time")
        alloc = float(ob.get("allocated_value", 0))
        dur   = summary["duration_months"]
        params = ob.get("recognition_params", {})

        if rec == "over_time":
            entry = {
                "id": ob["id"], "name": ob["name"], "pattern": "over_time",
                "monthly_amount": round(alloc / dur, 2),
                "periods": dur, "total": alloc,
            }
        elif rec in ("point_in_time", "upfront"):
            entry = {
                "id": ob["id"], "name": ob["name"], "pattern": rec,
                "completion_date": params.get("estimated_completion_date"),
                "amount": alloc,
            }
        else:  # usage_based
            entry = {
                "id": ob["id"], "name": ob["name"], "pattern": rec,
                "estimated_monthly": round(alloc / dur, 2) if dur else 0,
                "total_constrained": alloc,
            }
        recognition_summary.append(entry)

    step5 = {
        "recognition_summary": recognition_summary,
        "total_revenue": tcv,
    }

    return {
        "step_1": step1,
        "step_2": step2,
        "step_3": step3,
        "step_4": step4,
        "step_5": step5,
    }
