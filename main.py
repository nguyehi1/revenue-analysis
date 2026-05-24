import json
import asyncio
import logging
import os
from pathlib import Path
from typing import AsyncGenerator

from fastapi import FastAPI, HTTPException
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, StreamingResponse
from pydantic import BaseModel

try:
    from dotenv import load_dotenv
    load_dotenv(Path(__file__).parent / ".env", override=True)
except ImportError:
    pass

from utils.calculation_engine import generate_schedule, build_reasoning
from utils.llm_judgments import explain_steps

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

app = FastAPI(title="ASC 606 Revenue Calculator")


# ---------------------------------------------------------------------------
# Load examples at startup
# ---------------------------------------------------------------------------

def _load_examples() -> list:
    examples = []
    examples_dir = Path(__file__).parent / "data" / "examples"
    for path in sorted(examples_dir.glob("s*.json")):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            stem = path.stem
            parts = stem.split("_", 1)
            num = parts[0].upper()
            label = parts[1].replace("_", " ").title() if len(parts) > 1 else stem
            examples.append({"key": f"{num} — {label}", "data": data})
        except Exception as e:
            logger.warning("Could not load %s: %s", path.name, e)
    return examples


EXAMPLES = _load_examples()


# ---------------------------------------------------------------------------
# API routes
# ---------------------------------------------------------------------------

@app.get("/api/examples")
def list_examples():
    result = []
    for ex in EXAMPLES:
        d = ex["data"]
        order_forms = d.get("order_forms") or []

        # TCV: top-level wins; fall back to sum of order form TCVs for MSA-style contracts
        tcv = d.get("total_contract_value") or sum(
            of.get("total_contract_value", 0) for of in order_forms
        )

        # Dates: top-level wins; for MSA use first OF start and last OF end
        start_date = d.get("start_date") or (order_forms[0].get("start_date", "") if order_forms else "")
        end_date   = d.get("end_date")   or (order_forms[-1].get("end_date", "")  if order_forms else "")

        # POBs: top-level wins; for MSA sum across all order forms
        if d.get("performance_obligations"):
            pobs = d["performance_obligations"]
        else:
            pobs = [p for of in order_forms for p in of.get("performance_obligations", [])]

        result.append({
            "key": ex["key"],
            "vendor": d.get("vendor", ""),
            "customer": d.get("customer", ""),
            "industry": d.get("industry", ""),
            "summary": d.get("scenario_summary", ""),
            "start_date": start_date,
            "end_date": end_date,
            "total_contract_value": tcv or 0,
            "num_pobs": len(pobs),
        })
    return result


@app.get("/api/examples/{index}")
def get_example(index: int):
    if index < 0 or index >= len(EXAMPLES):
        raise HTTPException(status_code=404, detail="Example not found")
    return EXAMPLES[index]["data"]


class ContractRequest(BaseModel):
    contract: dict


@app.post("/api/calculate")
def calculate(req: ContractRequest):
    try:
        result = generate_schedule(req.contract)
        step_data = build_reasoning(req.contract, result)
        return {"result": result, "step_data": step_data}
    except Exception as e:
        logger.exception("Calculation failed")
        raise HTTPException(status_code=400, detail=str(e))


class ReasoningRequest(BaseModel):
    contract: dict
    step_data: dict


@app.post("/api/reasoning")
async def stream_reasoning(req: ReasoningRequest):
    async def generate() -> AsyncGenerator[str, None]:
        try:
            reasoning = await asyncio.to_thread(explain_steps, req.contract, req.step_data)
            for step_key in ["step_1", "step_2", "step_3", "step_4", "step_5"]:
                text = reasoning.get(step_key, "")
                if text:
                    yield f"data: {json.dumps({'step': step_key, 'text': text})}\n\n"
                    await asyncio.sleep(0.1)
            yield "data: [DONE]\n\n"
        except Exception as e:
            logger.error("Reasoning stream failed: %s", e)
            yield f"data: {json.dumps({'error': str(e)})}\n\n"
            yield "data: [DONE]\n\n"

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


# ---------------------------------------------------------------------------
# Static files — must be last
# ---------------------------------------------------------------------------

app.mount("/static", StaticFiles(directory="static"), name="static")


@app.get("/")
def index():
    return FileResponse("static/index.html")
