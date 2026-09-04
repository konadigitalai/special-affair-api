import re

FORBIDDEN_PATTERNS = {
    "change_price": r"\b(change|set|lower|increase)\b.{0,30}\bprice\b",
    "approve_refund": r"\b(approve|issue)\b.{0,30}\brefund\b",
    "change_payment": r"\b(mark|set|change)\b.{0,30}\b(payment|paid)\b",
    "modify_inventory": r"\b(change|set|add)\b.{0,30}\b(stock|inventory)\b",
}


def prohibited_intent(message: str) -> str | None:
    lowered = message.lower()
    return next((name for name, pattern in FORBIDDEN_PATTERNS.items() if re.search(pattern, lowered)), None)

