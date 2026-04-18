from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import time
 
from drug_mapper import INDIAN_DRUG_MAP
from rxnorm import get_rxcui, get_drug_info
from interactions import check_interactions
from utils import (
    logger,
    interaction_cache, make_cache_key,
    smart_lookup,
    get_fuzzy_suggestions,
    sanitise,
)
 
DISCLAIMER = (
    "This tool is for informational purposes only and does not replace "
    "professional medical advice. Always consult a licensed doctor or "
    "pharmacist before taking any combination of medicines."
)
 
# ──────────────────────────────────────────────
# App setup
# ──────────────────────────────────────────────
app = FastAPI(
    title="Indian Drug Interaction Checker API",
    description="Check drug-drug interactions using Indian brand names.",
    version="2.0.0",
)
 
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
 
 
# ──────────────────────────────────────────────
# Request models
# ──────────────────────────────────────────────
class DrugListRequest(BaseModel):
    drugs: list[str]
 
class DrugResolveRequest(BaseModel):
    name: str
 
 
# ──────────────────────────────────────────────
# Basic routes
# ──────────────────────────────────────────────
@app.get("/")
def root():
    return {"message": "Drug Interaction Checker API is running", "version": "2.0.0"}
 
 
@app.get("/health")
def health_check():
    return {"status": "ok"}
 
 
# ──────────────────────────────────────────────
# NEW: /search-drug — autocomplete / suggestions
# ──────────────────────────────────────────────
@app.get("/search-drug")
def search_drug(q: str = Query(..., min_length=2, description="Partial drug name")):
    """
    Search for drug names matching a query string.
    Returns top fuzzy matches — use for autocomplete dropdown in frontend.
 
    Example: GET /search-drug?q=dol
    Returns: ["Dolo 650", "Dolo", "Dolonex"]
    """
    logger.info(f"SEARCH  | query='{q}'")
    results = get_fuzzy_suggestions(q, limit=8)
    return {
        "query": q,
        "results": results,
        "total": len(results),
    }
 
 
# ──────────────────────────────────────────────
# NEW: /list-drugs — full drug list for frontend
# ──────────────────────────────────────────────
@app.get("/list-drugs")
def list_drugs():
    """
    Returns all drug brand names in the mapper.
    Frontend can use this to build a full searchable dropdown.
    """
    drugs = [
        {"brand": brand, "generic": generic}
        for brand, generic in sorted(INDIAN_DRUG_MAP.items())
    ]
    return {
        "total": len(drugs),
        "drugs": drugs,
    }
 
 
# ──────────────────────────────────────────────
# /resolve-drug — test a single drug
# ──────────────────────────────────────────────
@app.post("/resolve-drug")
async def resolve_drug(req: DrugResolveRequest):
    """
    Resolve a single Indian brand name to generic + RXCUI.
    Useful for testing individual drugs in Swagger / Postman.
    """
    logger.info(f"RESOLVE | input='{req.name}'")
    lookup = smart_lookup(req.name)
 
    if lookup["match_type"] == "not_found":
        raise HTTPException(
            status_code=404,
            detail={
                "message": f"'{req.name}' not found.",
                "suggestion": lookup["suggestion"],
            }
        )
 
    try:
        rxcui = await get_rxcui(lookup["search_name"])
    except Exception as e:
        raise HTTPException(status_code=503, detail=f"RxNorm API error: {str(e)}")
 
    if not rxcui:
        raise HTTPException(
            status_code=404,
            detail={
                "message": f"Could not find RxNorm ID for '{lookup['search_name']}'.",
                "suggestion": lookup["suggestion"] or "Try a different spelling.",
            }
        )
 
    try:
        info = await get_drug_info(rxcui)
    except Exception:
        info = {"name": "Unknown"}
 
    return {
        "input": req.name,
        "sanitised": sanitise(req.name),
        "match_type": lookup["match_type"],
        "matched_brand": lookup["matched_brand"],
        "fuzzy_score": lookup["fuzzy_score"],
        "generic_name": lookup["generic"] or lookup["search_name"],
        "rxcui": rxcui,
        "rxnorm_name": info.get("name"),
        "disclaimer": DISCLAIMER,
    }
 
 
# ──────────────────────────────────────────────
# /check-interactions — main route
# ──────────────────────────────────────────────
@app.post("/check-interactions")
async def check_drug_interactions(req: DrugListRequest):
    """
    Main endpoint. Takes 2–10 Indian brand names, resolves them,
    and returns drug interaction results with severity + color.
 
    Example:
    {
        "drugs": ["Dolo 650", "Ecosprin", "Pan 40"]
    }
    """
    start_time = time.time()
 
    # ── Validate input count ────────────────────────────────────────────
    if len(req.drugs) < 2:
        raise HTTPException(status_code=400, detail="Please provide at least 2 drug names.")
    if len(req.drugs) > 10:
        raise HTTPException(status_code=400, detail="Maximum 10 drugs allowed per check.")
 
    logger.info(f"REQUEST | drugs={req.drugs}")
 
    resolved_drugs = []
    failed_drugs   = []
 
    # ── Resolve each drug name ──────────────────────────────────────────
    for raw_name in req.drugs:
        raw_name = raw_name.strip()
        if not raw_name:
            continue
 
        # Sanitise + smart lookup (exact → fuzzy → direct)
        lookup = smart_lookup(raw_name)
        logger.info(
            f"  LOOKUP | '{raw_name}' → '{lookup['search_name']}' "
            f"[{lookup['match_type']}, score={lookup['fuzzy_score']}]"
        )
 
        try:
            rxcui = await get_rxcui(lookup["search_name"])
        except Exception as e:
            raise HTTPException(
                status_code=503,
                detail=f"RxNorm API error for '{raw_name}': {str(e)}"
            )
 
        if not rxcui:
            failed_drugs.append({
                "input": raw_name,
                "sanitised": sanitise(raw_name),
                "match_type": lookup["match_type"],
                "matched_brand": lookup["matched_brand"],
                "reason": "Not found in RxNorm database.",
                "suggestion": lookup["suggestion"],
            })
            logger.warning(f"  FAILED | '{raw_name}' not found in RxNorm")
            continue
 
        resolved_drugs.append({
            "input": raw_name,
            "sanitised": sanitise(raw_name),
            "match_type": lookup["match_type"],
            "matched_brand": lookup["matched_brand"],
            "fuzzy_score": lookup["fuzzy_score"],
            "generic": lookup["generic"] or lookup["search_name"],
            "rxcui": rxcui,
        })
 
    # ── Need at least 2 resolved drugs ─────────────────────────────────
    if len(resolved_drugs) < 2:
        logger.warning(f"  ABORTED | only {len(resolved_drugs)} drugs resolved")
        raise HTTPException(
            status_code=422,
            detail={
                "message": "Could not resolve enough drugs to check interactions.",
                "resolved": resolved_drugs,
                "failed": failed_drugs,
                "tip": "Check spelling, or use generic names (e.g. 'paracetamol').",
                "help": "See all supported drugs at GET /list-drugs",
            }
        )
 
    # ── Check cache first ───────────────────────────────────────────────
    rxcui_list = [d["rxcui"] for d in resolved_drugs]
    cache_key  = make_cache_key(rxcui_list)
 
    if cache_key in interaction_cache:
        cached = interaction_cache[cache_key]
        elapsed = round((time.time() - start_time) * 1000)
        logger.info(f"  CACHE HIT | key={cache_key} | {elapsed}ms")
        return {
            **cached,
            "from_cache": True,
            "response_ms": elapsed,
        }
 
    # ── Call RxNav interaction API ──────────────────────────────────────
    try:
        interaction_data = await check_interactions(resolved_drugs)

    except Exception as e:
        raise HTTPException(
            status_code=503,
            detail=f"OpenFDA Interaction API error: {str(e)}"
        )
 
    elapsed = round((time.time() - start_time) * 1000)
    summary = build_summary(interaction_data["interactions"])
 
    logger.info(
        f"  RESULT | status={summary['status']} | "
        f"interactions={len(interaction_data['interactions'])} | {elapsed}ms"
    )
 
    # ── Build response ──────────────────────────────────────────────────
    response = {
        "resolved_drugs": resolved_drugs,
        "failed_drugs": failed_drugs,
        "has_interactions": interaction_data["has_interactions"],
        "interactions": interaction_data["interactions"],
        "summary": summary,
        "disclaimer": DISCLAIMER,
        "from_cache": False,
        "response_ms": elapsed,
    }
 
    # Store in cache
    interaction_cache[cache_key] = response
 
    return response
 
 
# ──────────────────────────────────────────────
# Summary builder
# ──────────────────────────────────────────────
def build_summary(interactions: list) -> dict:
    if not interactions:
        return {
            "status": "safe",
            "color": "green",
            "message": "No known interactions found between these drugs.",
        }
 
    severities = [i["severity"] for i in interactions]
 
    if "high" in severities:
        return {
            "status": "dangerous",
            "color": "red",
            "message": "Dangerous interaction found! Do NOT take these drugs together without consulting a doctor.",
        }
    elif "moderate" in severities:
        return {
            "status": "caution",
            "color": "orange",
            "message": "Moderate interaction detected. Consult your doctor before taking these together.",
        }
    else:
        return {
            "status": "mild",
            "color": "yellow",
            "message": "Minor interaction detected. Generally safe, but inform your doctor.",
        }