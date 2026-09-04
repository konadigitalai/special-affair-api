from uuid import UUID

from pydantic import ValidationError
import pytest

from app.modules.checkout.router import CheckoutRequest, derive_order_token


def valid_checkout() -> dict[str, object]:
    return {"cart_id": "018f0f5d-83b7-7cc8-95d8-1ebdba28d001", "email": "buyer@example.com", "phone": "+919876543210", "shipping_address": {"full_name": "Test Buyer", "street": "1 Test Street", "city": "Hyderabad", "state": "Telangana", "pin_code": "500001", "country": "IN"}, "payment_method": "cod"}


def test_raw_card_data_is_rejected() -> None:
    payload = valid_checkout()
    payload["card_number"] = "4111111111111111"
    with pytest.raises(ValidationError):
        CheckoutRequest.model_validate(payload)


def test_order_token_is_stable_for_idempotent_replay() -> None:
    order_id = UUID("018f0f5d-83b7-7cc8-95d8-1ebdba28d001")
    assert derive_order_token(order_id, "request-1", "secret") == derive_order_token(order_id, "request-1", "secret")
    assert derive_order_token(order_id, "request-1", "secret") != derive_order_token(order_id, "request-2", "secret")
