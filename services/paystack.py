import hashlib
import hmac
import os
from typing import Any

import httpx


class PaystackError(RuntimeError):
    def __init__(self, message: str, status_code: int = 502):
        super().__init__(message)
        self.status_code = status_code


def naira_to_kobo(amount_naira: int) -> int:
    if amount_naira <= 0:
        raise ValueError("Payment amount must be greater than zero")
    return amount_naira * 100


class PaystackService:
    def __init__(
        self,
        secret_key: str | None = None,
        base_url: str | None = None,
        callback_url: str | None = None,
        timeout: float = 15.0,
    ):
        self.secret_key = secret_key or os.getenv("PAYSTACK_SECRET_KEY")
        self.base_url = (
            base_url or os.getenv("PAYSTACK_BASE_URL") or "https://api.paystack.co"
        ).rstrip("/")
        self.callback_url = callback_url or os.getenv("PAYSTACK_CALLBACK_URL")
        self.timeout = timeout

    def _headers(self) -> dict[str, str]:
        if not self.secret_key:
            raise PaystackError("Paystack is not configured", status_code=503)
        return {
            "Authorization": f"Bearer {self.secret_key}",
            "Content-Type": "application/json",
        }

    def _request(
        self,
        method: str,
        path: str,
        *,
        json: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        try:
            response = httpx.request(
                method,
                f"{self.base_url}{path}",
                headers=self._headers(),
                json=json,
                timeout=self.timeout,
            )
            payload = response.json()
        except (httpx.HTTPError, ValueError) as exc:
            raise PaystackError("Unable to communicate with Paystack") from exc

        if not response.is_success or not payload.get("status"):
            message = payload.get("message", "Paystack request failed")
            raise PaystackError(message)
        return payload["data"]

    def initialize_transaction(
        self,
        *,
        email: str,
        amount_kobo: int,
        reference: str,
        order_id: str,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "email": email,
            "amount": amount_kobo,
            "currency": "NGN",
            "reference": reference,
            "metadata": {
                "order_id": order_id,
                "cancel_action": "Full refund is available for 30 minutes after payment",
            },
        }
        if self.callback_url:
            payload["callback_url"] = self.callback_url
        return self._request("POST", "/transaction/initialize", json=payload)

    def verify_transaction(self, reference: str) -> dict[str, Any]:
        return self._request("GET", f"/transaction/verify/{reference}")

    def create_full_refund(
        self,
        *,
        transaction_reference: str,
        merchant_note: str,
    ) -> dict[str, Any]:
        return self._request(
            "POST",
            "/refund",
            json={
                "transaction": transaction_reference,
                "merchant_note": merchant_note,
            },
        )

    def verify_webhook_signature(self, raw_body: bytes, signature: str | None) -> bool:
        if not self.secret_key or not signature:
            return False
        expected = hmac.new(
            self.secret_key.encode(),
            raw_body,
            hashlib.sha512,
        ).hexdigest()
        return hmac.compare_digest(expected, signature)


paystack_service = PaystackService()