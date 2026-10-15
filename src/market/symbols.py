"""Symbol normalisation and instrument metadata.

The framework never guesses an instrument. When a symbol cannot be
classified it is still accepted as an "unknown" instrument, but
provider mappings return None so no data is fabricated.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from src.utils.errors import ValidationError
from src.utils.validation import clean_symbol_text

FOREX_CURRENCIES = {
    "USD", "EUR", "GBP", "JPY", "CHF", "AUD", "NZD", "CAD", "SEK", "NOK",
    "DKK", "PLN", "HUF", "CZK", "TRY", "ZAR", "MXN", "SGD", "HKD", "CNH", "CNY",
}

METALS = {
    "XAU": ("Gold vs US Dollar", 0.1, 2),
    "XAG": ("Silver vs US Dollar", 0.01, 3),
    "XPT": ("Platinum vs US Dollar", 0.1, 2),
    "XPD": ("Palladium vs US Dollar", 0.1, 2),
}

CRYPTO_BASES = {
    "BTC", "ETH", "SOL", "XRP", "ADA", "DOGE", "BNB", "LTC", "DOT", "AVAX",
    "LINK", "MATIC", "TON", "TRX", "SHIB", "XMR", "ETC", "ATOM", "NEAR", "APT",
    "ARB", "OP", "SUI", "SEI", "INJ", "TIA", "PEPE", "WIF", "BCH", "UNI", "AAVE",
}

CRYPTO_QUOTES = {"USDT", "USDC", "BUSD", "FDUSD", "TUSD", "USD", "BTC", "ETH", "EUR", "TRY"}

_ALIASES = {
    "GOLD": "XAUUSD",
    "SILVER": "XAGUSD",
    "XAU": "XAUUSD",
    "SILVERUSD": "XAGUSD",
    "WTI": "USOIL",
    "OIL": "USOIL",
}


@dataclass(frozen=True)
class SymbolInfo:
    symbol: str
    asset_class: str  # forex | metal | crypto | stock | index | unknown
    base: str
    quote: str
    pip_size: float
    price_decimals: int
    description: str = ""

    @property
    def is_crypto(self) -> bool:
        return self.asset_class == "crypto"

    @property
    def is_forex_like(self) -> bool:
        return self.asset_class in ("forex", "metal")


def _guess_pip_size(base: str, quote: str, asset_class: str) -> float:
    if asset_class == "crypto":
        return 1.0
    if base in METALS and quote == "USD":
        return METALS[base][1]
    if quote == "JPY":
        return 0.01
    return 0.0001


def _guess_decimals(asset_class: str, quote: str) -> int:
    if asset_class == "crypto":
        return 2
    if asset_class == "metal":
        return 2
    if quote == "JPY":
        return 3
    if asset_class == "forex":
        return 5
    return 4


def resolve_symbol(raw: str) -> SymbolInfo:
    """Resolve free-form user input into a SymbolInfo.

    Examples: XAUUSD, xau/usd, BTCUSDT, BTC-USD, EURUSD, GOLD.
    """
    cleaned = clean_symbol_text(raw)
    cleaned = _ALIASES.get(cleaned, cleaned)

    base = ""
    quote = ""
    asset_class = "unknown"
    description = ""

    # Crypto suffix detection first (e.g. BTCUSDT, ETHBTC).
    for suffix in sorted(CRYPTO_QUOTES, key=len, reverse=True):
        if cleaned.endswith(suffix) and len(cleaned) > len(suffix):
            candidate_base = cleaned[: -len(suffix)]
            if candidate_base in CRYPTO_BASES and (
                suffix != "USD" or candidate_base not in {"", "XAU"}
            ):
                base, quote, asset_class = candidate_base, suffix, "crypto"
                description = f"{candidate_base} crypto pair vs {suffix}"
                break

    if asset_class == "unknown" and len(cleaned) >= 6:
        candidate_base = cleaned[:3]
        candidate_quote = cleaned[3:]
        if candidate_base in METALS and candidate_quote in FOREX_CURRENCIES:
            base, quote, asset_class = candidate_base, candidate_quote, "metal"
            description = f"{METALS[candidate_base][0]}"
        elif candidate_base in FOREX_CURRENCIES and candidate_quote in FOREX_CURRENCIES:
            base, quote, asset_class = candidate_base, candidate_quote, "forex"
            description = f"{candidate_base}/{candidate_quote} currency pair"

    if asset_class == "unknown":
        if cleaned in ("USOIL", "UKOIL", "XBRUSD", "XTIUSD"):
            base, quote, asset_class = cleaned[:-3] or "OIL", "USD", "index"
            description = "crude oil"
        else:
            match = re.match(r"^([A-Z]{1,6})([0-9]{0,4})$", cleaned)
            if match:
                base = match.group(1)
                quote = ""
                description = f"unclassified instrument {cleaned}"
            else:
                raise ValidationError(f"cannot interpret symbol: {raw!r}")

    pip = _guess_pip_size(base, quote, asset_class)
    decimals = _guess_decimals(asset_class, quote)
    return SymbolInfo(
        symbol=cleaned,
        asset_class=asset_class,
        base=base,
        quote=quote,
        pip_size=pip,
        price_decimals=decimals,
        description=description or cleaned,
    )
