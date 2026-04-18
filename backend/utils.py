"""
utils.py — Input sanitisation, fuzzy matching, and cache
All helper functions used by main.py
"""
import re
import logging
from thefuzz import process
from cachetools import TTLCache
 
from drug_mapper import INDIAN_DRUG_MAP
 
# ──────────────────────────────────────────────────────
# Logger — prints timestamped request logs to terminal
# ──────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="[%(asctime)s] %(levelname)s → %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("drug_checker")
 
 
# ──────────────────────────────────────────────────────
# Cache — stores interaction results for 1 hour
# Max 500 unique drug combinations stored at a time
# ──────────────────────────────────────────────────────
interaction_cache = TTLCache(maxsize=500, ttl=3600)
 
def make_cache_key(rxcui_list: list[str]) -> str:
    """Sorted so ['161','1191'] and ['1191','161'] give same key."""
    return "|".join(sorted(rxcui_list))
 
 
# ──────────────────────────────────────────────────────
# Input Sanitisation
# ──────────────────────────────────────────────────────
def sanitise(name: str) -> str:
    """
    Clean up user input before lookup:
      - Strip leading/trailing whitespace
      - Lowercase
      - Collapse multiple spaces into one
      - Remove special characters except letters, digits, spaces, hyphen
      Examples:
        "DOLO  650 !!"  → "dolo 650"
        "  Pan-40  "    → "pan-40"
        "crocin@#advance" → "crocin advance"
    """
    name = name.strip().lower()
    name = re.sub(r"[^a-z0-9\s\-]", " ", name)   # remove special chars
    name = re.sub(r"\s+", " ", name).strip()        # collapse spaces
    return name
 
 
# ──────────────────────────────────────────────────────
# Fuzzy Matching
# ──────────────────────────────────────────────────────
ALL_DRUG_NAMES = list(INDIAN_DRUG_MAP.keys())
FUZZY_THRESHOLD = 80  # minimum similarity score (0-100) to accept a match
 
def fuzzy_lookup(name: str) -> tuple[str | None, str | None, int]:
    """
    Try to find the closest drug name in the mapper using fuzzy matching.
    Returns (matched_brand, generic_name, score).
    Returns (None, None, 0) if no good match found.
 
    Examples:
      "dolo650"      → ("dolo 650",  "paracetamol", 90)
      "crocin advanc"→ ("crocin advance", "paracetamol", 92)
      "xyz abc"      → (None, None, 0)
    """
    sanitised = sanitise(name)
    result = process.extractOne(sanitised, ALL_DRUG_NAMES)
    if result is None:
        return None, None, 0
    matched_brand, score = result[0], result[1]
    if score >= FUZZY_THRESHOLD:
        return matched_brand, INDIAN_DRUG_MAP[matched_brand], score
    return None, None, score
 
 
def smart_lookup(name: str) -> dict:
    """
    Full lookup pipeline for one drug name:
    1. Sanitise input
    2. Exact match in mapper
    3. Fuzzy match in mapper
    4. Fall back to using the name directly as generic (e.g. 'metformin')
    5. If none work, suggest what to do
 
    Returns a dict with:
      {
        "search_name": str,        # what to send to RxNorm
        "generic": str | None,
        "match_type": "exact" | "fuzzy" | "direct" | "not_found",
        "matched_brand": str | None,
        "fuzzy_score": int,
        "suggestion": str | None   # helpful message for the user
      }
    """
    sanitised = sanitise(name)
 
    # Step 1 — exact match
    if sanitised in INDIAN_DRUG_MAP:
        return {
            "search_name": INDIAN_DRUG_MAP[sanitised],
            "generic": INDIAN_DRUG_MAP[sanitised],
            "match_type": "exact",
            "matched_brand": sanitised,
            "fuzzy_score": 100,
            "suggestion": None,
        }
 
    # Step 2 — fuzzy match
    matched_brand, generic, score = fuzzy_lookup(sanitised)
    if generic:
        return {
            "search_name": generic,
            "generic": generic,
            "match_type": "fuzzy",
            "matched_brand": matched_brand,
            "fuzzy_score": score,
            "suggestion": f"Did you mean '{matched_brand}'?",
        }
 
    # Step 3 — try directly as generic name (e.g. user typed 'metformin')
    return {
        "search_name": sanitised,
        "generic": None,
        "match_type": "direct",
        "matched_brand": None,
        "fuzzy_score": 0,
        "suggestion": build_not_found_suggestion(sanitised),
    }
 
 
def get_fuzzy_suggestions(name: str, limit: int = 5) -> list[dict]:
    """
    Return top N fuzzy matches for autocomplete / search-drug route.
    Used by the /search-drug endpoint.
    """
    sanitised = sanitise(name)
    if len(sanitised) < 2:
        return []
    results = process.extract(sanitised, ALL_DRUG_NAMES, limit=limit)
    return [
        {
            "brand": r[0],
            "generic": INDIAN_DRUG_MAP[r[0]],
            "score": r[1],
        }
        for r in results if r[1] >= 50   # lower threshold for suggestions
    ]
 
 
# ──────────────────────────────────────────────────────
# Not-found suggestion builder
# ──────────────────────────────────────────────────────
def build_not_found_suggestion(name: str) -> str:
    """
    When a drug is not found anywhere, return a helpful message
    telling the user what they can do.
    """
    return (
        f"'{name}' was not found in our Indian drug database. "
        f"Try one of these options: "
        f"(1) Check the spelling. "
        f"(2) Use the generic name instead (e.g. 'paracetamol' instead of 'Dolo 650'). "
        f"(3) Try a known brand name from our list at /list-drugs. "
        f"(4) If it's a new or rare drug, use the generic/chemical name directly."
    )