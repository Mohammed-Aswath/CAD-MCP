import difflib
from typing import List, Optional

SYMBOL_ALIASES = {
    "pump": "pump",
    "centrifugal pump": "pump",
    "valve": "4_way_valve",
    "3 way valve": "3_way_valve",
    "3-way valve": "3_way_valve",
    "4 way valve": "4_way_valve",
    "4-way valve": "4_way_valve",
    "angle valve": "angle_valve",
    "ball valve": "ball_valve",
    "check valve": "check_valve",
    "blind flange": "blind_flange",
    "diaphragm valve": "diaphragm_valve",
    "gauge": "gauge",
    "pressure gauge": "gauge",
    "sensor": "sensor",
    "flow sensor": "sensor",
    "motor": "motor",
    "vessel": "vessel",
    "tank": "tank",
    "instrument": "gauge",
}


def resolve_symbol_name(user_term: str, available_symbols: List[str]) -> str:
    normalized = (user_term or "").strip().lower()
    if not normalized:
        return user_term

    if normalized in SYMBOL_ALIASES:
        return SYMBOL_ALIASES[normalized]

    lower_symbols = {symbol.lower(): symbol for symbol in available_symbols}
    if normalized in lower_symbols:
        return lower_symbols[normalized]

    suggestions = difflib.get_close_matches(normalized, list(lower_symbols.keys()), n=1, cutoff=0.65)
    if suggestions:
        return lower_symbols[suggestions[0]]

    return user_term


def suggest_symbol_name(user_term: str, available_symbols: List[str]) -> Optional[str]:
    normalized = (user_term or "").strip().lower()
    lower_symbols = {symbol.lower(): symbol for symbol in available_symbols}
    suggestions = difflib.get_close_matches(normalized, list(lower_symbols.keys()), n=3, cutoff=0.5)
    return suggestions[0] if suggestions else None
