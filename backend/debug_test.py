"""
Run this directly:  python debug_test.py
This bypasses FastAPI and tests each step independently.
"""
import asyncio
import httpx

RXNORM_BASE  = "https://rxnav.nlm.nih.gov/REST"
RXNAV_BASE   = "https://rxnav.nlm.nih.gov/REST"

async def main():
    async with httpx.AsyncClient(timeout=15.0) as client:

        # ── STEP 1: Get RXCUI for paracetamol ──────────────────────────
        print("\n── STEP 1: RxNorm lookup for 'paracetamol' ──")
        url1 = f"{RXNORM_BASE}/rxcui.json"
        r1 = await client.get(url1, params={"name": "paracetamol", "search": 1})
        print("Status :", r1.status_code)
        d1 = r1.json()
        id_group = d1.get("idGroup") or {}
        rxcui_para = (id_group.get("rxnormId") or [None])[0]
        print("RXCUI  :", rxcui_para)

        # ── STEP 2: Get RXCUI for aspirin ───────────────────────────────
        print("\n── STEP 2: RxNorm lookup for 'aspirin' ──")
        r2 = await client.get(url1, params={"name": "aspirin", "search": 1})
        print("Status :", r2.status_code)
        d2 = r2.json()
        id_group2 = d2.get("idGroup") or {}
        rxcui_asp = (id_group2.get("rxnormId") or [None])[0]
        print("RXCUI  :", rxcui_asp)

        if not rxcui_para or not rxcui_asp:
            print("\nERROR: Could not get RXCUIs — RxNorm API may be down.")
            return

        # ── STEP 3: Check interaction URL ───────────────────────────────
        print(f"\n── STEP 3: RxNav interaction check ──")

        # Build URL directly — no params dict to avoid encoding issues
        rxcuis_str = f"{rxcui_para}+{rxcui_asp}"
        full_url = f"{RXNAV_BASE}/interaction/list.json?rxcuis={rxcuis_str}"
        print("Exact URL sent:", full_url)

        r3 = await client.get(full_url)
        print("Status :", r3.status_code)

        if r3.status_code == 200:
            d3 = r3.json()
            groups = d3.get("fullInteractionTypeGroup") or []
            print("Interactions found:", len(groups) > 0)
            if groups:
                for g in groups:
                    for t in (g.get("fullInteractionType") or []):
                        for p in (t.get("interactionPair") or []):
                            print("  ->", p.get("description", "")[:80])
            else:
                print("  -> No interactions (safe combination)")
        else:
            print("BODY:", r3.text[:300])

asyncio.run(main())