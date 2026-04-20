import re
import httpx

OPENFDA_LABEL_URL = "https://api.fda.gov/drug/label.json"

SEVERITY_COLORS = {
    "high": "red",
    "moderate": "orange",
    "low": "yellow",
    "unknown": "gray",
}

HIGH_KEYWORDS = [
    "contraindicated", "do not use", "fatal", "life-threatening",
    "do not administer", "must not", "should not be used",
    "should be avoided", "strongly advise",
    "avoid",
    "not recommended",
    "potentially fatal", "risk of death",
    "severe toxicity", "serious adverse", "severe interaction",
    "risk of serious",
    "severe bleeding", "serious bleeding", "major bleeding", "hemorrhage",
    "respiratory depression", "serotonin syndrome", "cardiac arrest",
    "severe hypotension", "anaphylaxis",
    "torsades de pointes", "QT prolongation", "severe CNS depression",
]

MODERATE_KEYWORDS = [
    "caution", "monitor closely", "monitor", "moderate",
    "may increase", "may decrease", "reduced clearance", "increased risk",
    "potentiate", "enhance", "inhibit", "bleeding risk", "inr",
    "anticoagulant effect", "reduce dose", "adjust dose", "closely monitor",
    "coadministration", "co-administration",
    "use with caution", "concurrent use", "concomitant use", "drug interaction",
]

LOW_KEYWORDS = [
    "minor", "mild", "minimal", "slight", "generally safe",
    "no clinically significant", "unlikely to be clinically significant",
]


def parse_severity(full_label_text: str) -> str:
    t = full_label_text.lower()
    if any(w in t for w in HIGH_KEYWORDS):
        return "high"
    elif any(w in t for w in MODERATE_KEYWORDS):
        return "moderate"
    elif any(w in t for w in LOW_KEYWORDS):
        return "low"
    return "unknown"


def clean_fda_text(text: str) -> str:
    text = re.sub(r'\b\d+\.\d+(\.\d+)?\s+', '', text)
    text = re.sub(
        r'\b([A-Z]{2,})(?:\s+[A-Z]{2,}){0,4}\b',
        lambda m: m.group().title(),
        text
    )
    text = re.sub(r'\s+', ' ', text).strip()
    return text


def extract_relevant_sentences(text: str, keyword: str, max_chars: int = 300) -> str:
    cleaned = clean_fda_text(text)
    sentences = re.split(r'(?<=[.!?])\s+', cleaned)
    sentences = [s.strip() for s in sentences if len(s.strip()) > 20]
    keyword_lower = keyword.lower()
    relevant = [s for s in sentences if keyword_lower in s.lower()]
    if not relevant:
        fallback = ' '.join(sentences[:2])
        return fallback[:max_chars].rsplit(' ', 1)[0] if len(fallback) > max_chars else fallback
    result_parts = []
    total = 0
    for sent in relevant:
        if total + len(sent) > max_chars and result_parts:
            break
        result_parts.append(sent)
        total += len(sent) + 1
    return ' '.join(result_parts)


async def fetch_interaction_text(generic_name: str, rxcui: str) -> str | None:
    queries = [
        f'openfda.rxcui:"{rxcui}"',
        f'openfda.generic_name:"{generic_name}"',
        f'openfda.substance_name:"{generic_name}"',
    ]
    async with httpx.AsyncClient(timeout=15.0) as client:
        for query in queries:
            try:
                resp = await client.get(OPENFDA_LABEL_URL, params={"search": query, "limit": 1})
                if resp.status_code != 200:
                    continue
                data = resp.json()
                results = data.get("results") or []
                if not results:
                    continue
                sections = results[0].get("drug_interactions") or []
                if sections:
                    return " ".join(sections)
            except Exception:
                continue
    return None


async def check_interactions(resolved_drugs: list[dict]) -> dict:
    if len(resolved_drugs) < 2:
        return {"has_interactions": False, "interactions": [], "message": "Need at least 2 drugs."}

    seen: set[str] = set()
    unique_drugs: list[dict] = []
    for d in resolved_drugs:
        if d["rxcui"] not in seen:
            seen.add(d["rxcui"])
            unique_drugs.append(d)

    label_texts: dict[str, str | None] = {}
    for drug in unique_drugs:
        label_texts[drug["rxcui"]] = await fetch_interaction_text(drug["generic"], drug["rxcui"])

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

            matched_full_text = None
            snippet = None
            matched_from = None

            text_a = label_texts.get(drug_a["rxcui"])
            if text_a and drug_b["generic"].lower() in text_a.lower():
                matched_full_text = text_a
                snippet = extract_relevant_sentences(text_a, drug_b["generic"])
                matched_from = drug_a["generic"]

            if not matched_full_text:
                text_b = label_texts.get(drug_b["rxcui"])
                if text_b and drug_a["generic"].lower() in text_b.lower():
                    matched_full_text = text_b
                    snippet = extract_relevant_sentences(text_b, drug_a["generic"])
                    matched_from = drug_b["generic"]

            if matched_full_text and snippet:
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