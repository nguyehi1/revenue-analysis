"""
LLM-powered judgment layer using the Google Gemini API.

Each function here handles one judgment call that requires reasoning,
not deterministic math.  The Python calculation engine calls these when:
  - An SSP is missing and needs to be estimated from context
  - A variable consideration constraint needs to be assessed
  - A contract modification type needs to be classified

Each function returns a dict with:
  value     — the numeric amount or string classification
  reasoning — human-readable explanation for audit trail

All heavy math (allocation, period schedules, balance computation) stays
in calculation_engine.py.  These functions only produce judgments that
feed into that math.
"""

from typing import Dict, Any, List, Optional
import json
import logging
import os

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Gemini client — re-reads key each call so .env changes take effect
# ---------------------------------------------------------------------------

def _call_gemini(prompt: str) -> str:
    import google.generativeai as genai
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        raise EnvironmentError("GEMINI_API_KEY is not set. Add it to your .env file.")
    genai.configure(api_key=api_key)
    model = genai.GenerativeModel("gemini-2.5-flash")
    response = model.generate_content(prompt)
    return response.text.strip()


def _parse_json(text: str) -> Dict[str, Any]:
    """Extract JSON from a Gemini response that may include prose."""
    text = text.strip()
    for start, end in [("```json", "```"), ("```", "```"), ("{", None)]:
        idx = text.find(start)
        if idx == -1:
            continue
        if end:
            end_idx = text.find(end, idx + len(start))
            candidate = text[idx + len(start): end_idx].strip() if end_idx != -1 else ""
        else:
            brace_count = 0
            candidate = ""
            for i, ch in enumerate(text[idx:], idx):
                if ch == "{":
                    brace_count += 1
                elif ch == "}":
                    brace_count -= 1
                    if brace_count == 0:
                        candidate = text[idx: i + 1]
                        break
        if candidate:
            try:
                return json.loads(candidate)
            except json.JSONDecodeError:
                continue
    raise ValueError(f"Could not parse JSON from response: {text[:200]}")


# ---------------------------------------------------------------------------
# Judgment 1 — SSP estimation
# ---------------------------------------------------------------------------

def estimate_ssp(
    pob_description: str,
    pob_name: str,
    tcv: float,
    other_obligations: Optional[List[Dict]] = None,
) -> Dict[str, Any]:
    other_context = ""
    if other_obligations:
        lines = [f"  - {ob.get('name')}: SSP ${ob.get('ssp', {}).get('amount', 'unknown')}"
                 for ob in other_obligations]
        other_context = "Other obligations in the contract:\n" + "\n".join(lines)

    prompt = f"""You are an ASC 606 revenue recognition expert.

Estimate the standalone selling price (SSP) for the following performance obligation.
The SSP is the price at which the entity would sell the good or service separately.

Obligation name: {pob_name}
Obligation description: {pob_description}
Total contract value: ${tcv:,.2f}
{other_context}

Return JSON only:
{{
  "value": <estimated SSP as a number>,
  "reasoning": "<2-3 sentence explanation citing the estimation approach used>"
}}"""

    try:
        raw = _call_gemini(prompt)
        result = _parse_json(raw)
        logger.info("SSP estimate for '%s': $%s", pob_name, result.get("value"))
        return result
    except Exception as e:
        logger.error("SSP estimation failed: %s", e)
        return {"value": 0.0, "reasoning": f"Estimation failed: {e}"}


# ---------------------------------------------------------------------------
# Judgment 2 — Variable consideration constraint
# ---------------------------------------------------------------------------

def assess_vc_constraint(
    pob_description: str,
    vc_description: str,
    scenarios: List[Dict],
    unconstrained_estimate: float,
) -> Dict[str, Any]:
    scenario_text = "\n".join(
        f"  {s.get('label', '')}: ${s.get('annual_amount', s.get('amount', 0)):,.2f} "
        f"(probability {s.get('probability', 0):.0%})"
        for s in scenarios
    )

    prompt = f"""You are an ASC 606 revenue recognition expert.

Assess whether the following variable consideration should be constrained per
ASC 606-10-32-11 (include VC only if probable that a significant reversal won't occur).

Performance obligation: {pob_description}
Variable consideration description: {vc_description}

Scenarios:
{scenario_text}

Unconstrained expected value: ${unconstrained_estimate:,.2f}

Determine the constrained amount to include in the transaction price.

Return JSON only:
{{
  "value": <constrained amount as a number>,
  "reasoning": "<2-3 sentence explanation citing reversal risk factors>"
}}"""

    try:
        raw = _call_gemini(prompt)
        result = _parse_json(raw)
        logger.info("VC constraint assessed: $%s", result.get("value"))
        return result
    except Exception as e:
        logger.error("VC constraint assessment failed: %s", e)
        return {"value": unconstrained_estimate, "reasoning": f"Assessment failed: {e}"}


# ---------------------------------------------------------------------------
# Judgment 3 — Modification classification
# ---------------------------------------------------------------------------

def classify_modification(
    modification_description: str,
    original_contract_summary: str,
) -> Dict[str, Any]:
    prompt = f"""You are an ASC 606 revenue recognition expert.

Classify the following contract modification under ASC 606-10-25-12 through 25-13.

Original contract: {original_contract_summary}
Modification: {modification_description}

Possible classifications:
  - prospective_new_contract: New distinct goods/services at their standalone selling price.
    Account for modification as a separate contract (no reallocation of original).
  - prospective_remaining: Modification is NOT a separate contract and remaining
    performance obligations ARE distinct. Terminate old contract, start new.
  - cumulative_catch_up: Modification is NOT a separate contract and remaining
    performance is NOT distinct. Adjust revenue in the current period (catch-up).

Return JSON only:
{{
  "value": "<one of the three types above>",
  "reasoning": "<2-3 sentence explanation citing the specific ASC 606 criteria>"
}}"""

    try:
        raw = _call_gemini(prompt)
        result = _parse_json(raw)
        logger.info("Modification classified as: %s", result.get("value"))
        return result
    except Exception as e:
        logger.error("Modification classification failed: %s", e)
        return {"value": "prospective_new_contract", "reasoning": f"Classification failed: {e}"}


# ---------------------------------------------------------------------------
# Judgment 4 — Full 5-step narrative
# ---------------------------------------------------------------------------

def explain_steps(contract: Dict[str, Any], step_data: Dict[str, Any]) -> Dict[str, str]:
    """
    Generate narrative reasoning for all five ASC 606 steps in a single call.

    Returns:
        {"step_1": "...", "step_2": "...", "step_3": "...", "step_4": "...", "step_5": "..."}
    """
    prompt = f"""You are a senior revenue recognition accountant writing a technical memo under ASC 606.

Analyze the following contract and the Python-calculated step data. For each of the five ASC 606 steps, write 3-5 sentences of clear, specific reasoning explaining WHY — not just what the numbers are. Cite relevant ASC 606 paragraph references where they add precision.

CONTRACT:
{json.dumps(contract, indent=2, default=str)}

STEP DATA (Python-calculated facts):
{json.dumps(step_data, indent=2, default=str)}

Guidelines per step:
- Step 1: Address the five criteria of ASC 606-10-25-1 (approval, rights, payment terms, commercial substance, collectability). Flag if any criterion requires judgment.
- Step 2: Apply the two-part distinctness test (ASC 606-10-25-19): (a) capable of being distinct — customer can benefit from it on its own; (b) distinct in context — not highly interrelated with other promises. State conclusion for each POB.
- Step 3: Identify all components of the transaction price. For variable consideration, state the estimation method and constraint rationale (ASC 606-10-32-11: probable significant reversal). Note if a significant financing component exists (ASC 606-10-32-15).
- Step 4: State the allocation method chosen (relative SSP or residual per ASC 606-10-32-31 through 32-35). Explain why. If SSPs were estimated, note the approach. Quantify any discount and explain its allocation.
- Step 5: For each POB, state the recognition criterion: over time (at least one of three criteria per ASC 606-10-25-27) or point-in-time (ASC 606-10-25-30). Explain why the chosen pattern applies.

Return valid JSON only — no prose outside the JSON:
{{
  "step_1": "<3-5 sentences>",
  "step_2": "<3-5 sentences>",
  "step_3": "<3-5 sentences>",
  "step_4": "<3-5 sentences>",
  "step_5": "<3-5 sentences>"
}}"""

    try:
        raw = _call_gemini(prompt)
        result = _parse_json(raw)
        logger.info("5-step reasoning generated successfully")
        return result
    except Exception as e:
        logger.error("explain_steps failed: %s", e)
        return {
            f"step_{i}": f"AI reasoning unavailable: {e}"
            for i in range(1, 6)
        }
