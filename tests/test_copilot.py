from app.ai.shopping_copilot.policy import prohibited_intent
from app.ai.shopping_copilot.retrieval import parse_price_limit


def test_price_limit_is_converted_to_minor_units() -> None:
    assert parse_price_limit("Show black bags under ₹5,000") == 500000


def test_protected_commerce_mutations_are_blocked() -> None:
    assert prohibited_intent("Change the price to 100") == "change_price"
    assert prohibited_intent("Approve this refund") == "approve_refund"


def test_normal_product_question_is_allowed() -> None:
    assert prohibited_intent("Show me black bags") is None
