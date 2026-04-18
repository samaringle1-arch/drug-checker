import httpx

RXNORM_BASE_URL = "https://rxnav.nlm.nih.gov/REST"


async def get_rxcui(generic_name: str) -> str | None:
    """
    Given a generic drug name (e.g. 'paracetamol'),
    return its RxNorm RXCUI identifier.
    Returns None if not found.
    """
    url = f"{RXNORM_BASE_URL}/rxcui.json"
    params = {"name": generic_name, "search": 1}

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.get(url, params=params)
            response.raise_for_status()
            data = response.json()

            # FIX: RxNorm returns "idGroup": null when drug not found
            # data.get("idGroup", {}) returns None when key exists but value is null
            # Using  or {}  ensures we always get a dict, never None
            id_group = data.get("idGroup") or {}
            rxcui_list = id_group.get("rxnormId") or []

            if rxcui_list:
                return rxcui_list[0]
            return None

    except httpx.TimeoutException:
        raise Exception(f"RxNorm API timed out for '{generic_name}'. Check your internet connection.")
    except httpx.HTTPStatusError as e:
        raise Exception(f"RxNorm API returned HTTP {e.response.status_code} for '{generic_name}'.")
    except Exception as e:
        raise Exception(f"RxNorm error for '{generic_name}': {str(e)}")


async def get_drug_info(rxcui: str) -> dict:
    """
    Get basic drug information from RxNorm using RXCUI.
    Returns name and synonym info.
    """
    url = f"{RXNORM_BASE_URL}/rxcui/{rxcui}/properties.json"

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.get(url)
            response.raise_for_status()
            data = response.json()

            # FIX: same null guard — properties can also be null
            props = data.get("properties") or {}
            return {
                "rxcui": rxcui,
                "name": props.get("name") or "Unknown",
                "synonym": props.get("synonym") or "",
            }

    except Exception:
        # Not critical — just return the RXCUI with no extra info
        return {"rxcui": rxcui, "name": "Unknown", "synonym": ""}