import base64
import json
import os
import sys
import urllib.parse
import urllib.request
import uuid
from typing import Optional


# Live PayPal credentials from environment
CLIENT_ID = os.environ.get("PAYPAL_CLIENT_ID")
CLIENT_SECRET = os.environ.get("PAYPAL_CLIENT_SECRET")


OAUTH_URL = "https://api-m.paypal.com/v1/oauth2/token"
PAYOUTS_URL = "https://api-m.paypal.com/v1/payments/payouts"


def get_access_token(client_id: str, client_secret: str) -> str:
  """Fetch OAuth2 access token from PayPal live API using client credentials."""
  data = urllib.parse.urlencode({"grant_type": "client_credentials"}).encode("utf-8")
  basic_auth = base64.b64encode(f"{client_id}:{client_secret}".encode("utf-8")).decode("ascii")

  request = urllib.request.Request(OAUTH_URL, data=data, method="POST")
  request.add_header("Authorization", f"Basic {basic_auth}")
  request.add_header("Content-Type", "application/x-www-form-urlencoded")
  request.add_header("Accept", "application/json")
  request.add_header("Accept-Language", "en_US")

  try:
    with urllib.request.urlopen(request) as response:
      body = response.read().decode("utf-8")
      payload = json.loads(body)
      token = payload.get("access_token")
      if not token:
        raise RuntimeError("No access_token in PayPal OAuth response")
      return token
  except Exception as error:
    raise RuntimeError(f"Failed to obtain PayPal access token: {error}") from error


def create_payout(access_token: str, payout_payload: dict, *, prefer_async: bool = True, request_id: Optional[str] = None) -> dict:
  """Create a payout via PayPal live API.

  When prefer_async is True, sends header Prefer: respond-async and expects HTTP 202.
  When False, uses sync mode and waits for processing completion.
  """
  url = PAYOUTS_URL if prefer_async else f"{PAYOUTS_URL}?sync_mode=true"
  request = urllib.request.Request(url, data=json.dumps(payout_payload).encode("utf-8"), method="POST")
  request.add_header("Authorization", f"Bearer {access_token}")
  request.add_header("Content-Type", "application/json")
  request.add_header("Accept", "application/json")
  if prefer_async:
    request.add_header("Prefer", "respond-async")
  # Idempotency per docs
  request.add_header("PayPal-Request-Id", request_id or f"req-{uuid.uuid4().hex}")

  try:
    with urllib.request.urlopen(request) as response:
      body = response.read().decode("utf-8")
      return json.loads(body)
  except urllib.error.HTTPError as http_error:
    error_body = http_error.read().decode("utf-8")
    raise RuntimeError(f"PayPal payout failed: HTTP {http_error.code} {error_body}") from http_error
  except Exception as error:
    raise RuntimeError(f"PayPal payout failed: {error}") from error


def get_payout_status(access_token: str, payout_batch_id: str) -> dict:
  """Fetch payout batch status by batch ID."""
  status_url = f"{PAYOUTS_URL}/{payout_batch_id}"
  request = urllib.request.Request(status_url, method="GET")
  request.add_header("Authorization", f"Bearer {access_token}")
  request.add_header("Accept", "application/json")

  try:
    with urllib.request.urlopen(request) as response:
      body = response.read().decode("utf-8")
      return json.loads(body)
  except urllib.error.HTTPError as http_error:
    error_body = http_error.read().decode("utf-8")
    raise RuntimeError(f"Fetch payout status failed: HTTP {http_error.code} {error_body}") from http_error
  except Exception as error:
    raise RuntimeError(f"Fetch payout status failed: {error}") from error


def _generate_sender_batch_id() -> str:
  # Keep it short yet unique per docs guidance
  return f"SB-{uuid.uuid4().hex[:16]}"


def _extract_batch_id(payout_response: dict) -> Optional[str]:
  # Typical location for v1 payouts
  batch_header = payout_response.get("batch_header") or payout_response.get("batchHeader")
  if isinstance(batch_header, dict):
    payout_batch_id = batch_header.get("payout_batch_id") or batch_header.get("payoutBatchId")
    if payout_batch_id:
      return payout_batch_id
  # Fallback: try links
  for link in payout_response.get("links", []) or []:
    href = link.get("href")
    if href and "/v1/payments/payouts/" in href:
      return href.rsplit("/", 1)[-1]
  return None


def main() -> None:
  # Update receivers before running in production
  payout_body = {
    "sender_batch_header": {
      # Unique per request; also used for idempotency on PayPal side
      "sender_batch_id": _generate_sender_batch_id(),
      "recipient_type": "EMAIL",
      "email_subject": "You have money!",
      "email_message": "You received a payment. Thanks for using our service!"
    },
    "items": [
      {
        "amount": {"value": "44.99", "currency": "USD"},
        "sender_item_id": "201403140101",
        "recipient_wallet": "PAYPAL",
        "receiver": "bookandwords@yahoo.com"
      },
      {
        "amount": {"value": "38.99", "currency": "USD"},
        "sender_item_id": "201403140102",
        "recipient_wallet": "PAYPAL",
        "receiver": "bookandwords@yahoo.com"
      }
    ]
  }

  try:
    if not CLIENT_ID or not CLIENT_SECRET:
      raise RuntimeError("Missing PAYPAL_CLIENT_ID or PAYPAL_CLIENT_SECRET environment variables")
    token = get_access_token(CLIENT_ID, CLIENT_SECRET)
    result = create_payout(token, payout_body, prefer_async=True)
    print(json.dumps(result, indent=2))

    # Try to extract batch id and fetch current status once
    payout_batch_id = _extract_batch_id(result)
    if payout_batch_id:
      status = get_payout_status(token, payout_batch_id)
      print("\nCurrent payout batch status:")
      print(json.dumps(status, indent=2))
  except Exception as error:
    print(str(error), file=sys.stderr)
    sys.exit(1)


if __name__ == "__main__":
  main()