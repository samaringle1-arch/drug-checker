import httpx

OPENFDA_LABEL_URL = "https://api.fda.gov/drug/label.json"

SEVERITY_COLORS = {
    "high": "red",
    "moderate": "orange",
    "low": "yellow",
    "unknown": "gray",
}

# Keywords scanned against the FULL label text, not just the snippet
HIGH_KEYWORDS = [
    "contraindicated","avoid", "do not use", "fatal", "life-threatening",
    "severe bleeding", "serious bleeding", "hemorrhage", "major bleeding",
    "do not administer", "must not", "should not be used",
]

MODERATE_KEYWORDS = [
    "caution", "monitor closely", "monitor", "moderate",
    "may increase", "may decrease", "reduced clearance", "increased risk",
    "potentiate", "enhance", "inhibit", "bleeding risk", "inr",
    "anticoagulant effect", "reduce dose", "adjust dose", "closely monitor",
    "coadministration", "co-administration",
]

LOW_KEYWORDS = [
    "minor", "mild", "minimal", "slight", "generally safe",
]


def parse_severity(full_label_text: str) -> str:
    """
    Scan the FULL label interaction text for severity keywords.
    Order: high → moderate → low → unknown.
    """
    t = full_label_text.lower()
    if any(w in t for w in HIGH_KEYWORDS):
        return "high"
    elif any(w in t for w in MODERATE_KEYWORDS):
        return "moderate"
    elif any(w in t for w in LOW_KEYWORDS):
        return "low"
    return "unknown"


def extract_snippet(text: str, keyword: str, context: int = 350) -> str:
    """
    Extract a readable snippet around the keyword mention for display.
    """
    idx = text.lower().find(keyword.lower())
    if idx == -1:
        return text[:context].strip()
    start = max(0, idx - 80)
    end = min(len(text), idx + context)
    snippet = text[start:end].strip()
    # Try to start at a sentence boundary
    if start > 0 and snippet and not snippet[0].isupper():
        dot = snippet.find(". ")
        if dot != -1 and dot < 80:
            snippet = snippet[dot + 2:]
    return snippet


async def fetch_interaction_text(generic_name: str, rxcui: str) -> str | None:
    """
    Fetch the full drug_interactions section from the FDA drug label.
    Tries RxCUI first (precise), then generic name, then substance name.
    """
    queries = [
        f'openfda.rxcui:"{rxcui}"',
        f'openfda.generic_name:"{generic_name}"',
        f'openfda.substance_name:"{generic_name}"',
    ]
    async with httpx.AsyncClient(timeout=15.0) as client:
        for query in queries:
            try:
                resp = await client.get(
                    OPENFDA_LABEL_URL,
                    params={"search": query, "limit": 1}
                )
                if resp.status_code != 200:
                    continue
                data = resp.json()
                results = data.get("results") or []
                if not results:
                    continue
                label = results[0]
                sections = label.get("drug_interactions") or []
                if sections:
                    return " ".join(sections)
            except Exception:
                continue
    return None


async def check_interactions(resolved_drugs: list[dict]) -> dict:
    """
    Check drug-drug interactions using OpenFDA drug label data.
    resolved_drugs: list of {"input": str, "generic": str, "rxcui": str}

    For each unique pair (A, B):
      - Fetch full FDA label drug_interactions text for A and B
      - Check if A's label mentions B's name (and vice versa)
      - Parse severity from the FULL label text (not just the snippet)
      - Extract a short readable snippet for display
    """
    if len(resolved_drugs) < 2:
        return {
            "has_interactions": False,
            "interactions": [],
            "message": "Need at least 2 drugs to check interactions.",
        }

    # Deduplicate by rxcui
    seen_rxcuis: set[str] = set()
    unique_drugs: list[dict] = []
    for d in resolved_drugs:
        if d["rxcui"] not in seen_rxcuis:
            seen_rxcuis.add(d["rxcui"])
            unique_drugs.append(d)

    # Step 1: Fetch full label text for each unique drug
    label_texts: dict[str, str | None] = {}
    for drug in unique_drugs:
        label_texts[drug["rxcui"]] = await fetch_interaction_text(
            drug["generic"], drug["rxcui"]
        )

    # Step 2: Check every unique pair
    interaction_results = []
    checked_pairs: set[tuple] = set()

    for drug_a in unique_drugs:
        for drug_b in unique_drugs:
            if drug_a["rxcui"] == drug_b["rxcui"]:
                continue
            pair_key = tuple(sorted([drug_a["rxcui"], drug_b["rxcui"]]))
            if pair_key in checked_pairs:
                continue
            checked_pairs.add(pair_key)

            matched_full_text = None  # full label text used for severity
            snippet = None            # short excerpt used for display
            matched_from = None       # which drug's label had the mention

            text_a = label_texts.get(drug_a["rxcui"])
            if text_a and drug_b["generic"].lower() in text_a.lower():
                matched_full_text = text_a
                snippet = extract_snippet(text_a, drug_b["generic"])
                matched_from = drug_a["generic"]

            if not matched_full_text:
                text_b = label_texts.get(drug_b["rxcui"])
                if text_b and drug_a["generic"].lower() in text_b.lower():
                    matched_full_text = text_b
                    snippet = extract_snippet(text_b, drug_a["generic"])
                    matched_from = drug_b["generic"]

            if matched_full_text and snippet:
                # KEY FIX: severity parsed from full label, not just the snippet
                severity = parse_severity(matched_full_text)
                interaction_results.append({
                    "drug1":       drug_a["generic"],
                    "drug2":       drug_b["generic"],
                    "severity":    severity,
                    "color":       SEVERITY_COLORS.get(severity, "gray"),
                    "description": snippet,
                    "source":      f"FDA label for {matched_from}",
                })

    return {
        "has_interactions": len(interaction_results) > 0,
        "interactions":     interaction_results,
    }