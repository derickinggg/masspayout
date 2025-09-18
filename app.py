import os
import json
from typing import List

from flask import Flask, render_template, request, redirect, url_for, flash, session

import mass


def parse_amounts(raw: str) -> List[str]:
  values: List[str] = []
  for token in raw.replace("\r", "\n").replace(",", "\n").split("\n"):
    token = token.strip()
    if not token:
      continue
    # Basic validation: two-decimal numeric
    try:
      amt = float(token)
      if amt <= 0:
        raise ValueError("Amount must be positive")
      values.append(f"{amt:.2f}")
    except Exception:
      raise ValueError(f"Invalid amount: {token}")
  if not values:
    raise ValueError("At least one amount is required")
  return values


def build_payout_body(email: str, amounts: List[str], currency: str, subject: str, message: str) -> dict:
  items = []
  for idx, amount in enumerate(amounts, start=1):
    items.append({
      "amount": {"value": amount, "currency": currency},
      "sender_item_id": f"web-{idx:03d}",
      "recipient_wallet": "PAYPAL",
      "receiver": email,
      "purpose": "GOODS"
    })

  return {
    "sender_batch_header": {
      "sender_batch_id": mass._generate_sender_batch_id(),
      "recipient_type": "EMAIL",
      "email_subject": subject,
      "email_message": message,
    },
    "items": items,
  }


BASE_DIR = os.path.dirname(os.path.abspath(__file__))


def create_app() -> Flask:
  # Explicitly set template_folder to ensure Jinja finds templates on Vercel
  app = Flask(__name__, template_folder=os.path.join(BASE_DIR, "templates"))
  app.secret_key = os.environ.get("FLASK_SECRET_KEY", os.urandom(16))

  @app.get("/")
  def index():
    default_email = os.environ.get("DEFAULT_PAYOUT_EMAIL", "")
    has_session_creds = bool(session.get("paypal_client_id") and session.get("paypal_client_secret"))
    return render_template("payout.html", default_email=default_email, has_session_creds=has_session_creds)

  @app.post("/payout")
  def create_payout_route():
    try:
      # Prefer credentials provided via form/session; fallback to environment
      form_client_id = request.form.get("client_id", "").strip()
      form_client_secret = request.form.get("client_secret", "").strip()
      if form_client_id and form_client_secret:
        session["paypal_client_id"] = form_client_id
        session["paypal_client_secret"] = form_client_secret

      client_id = session.get("paypal_client_id") or os.environ.get("PAYPAL_CLIENT_ID")
      client_secret = session.get("paypal_client_secret") or os.environ.get("PAYPAL_CLIENT_SECRET")
      if not client_id or not client_secret:
        flash("Provide PayPal Client ID/Secret in the form or set environment variables.", "error")
        return redirect(url_for("index"))

      email = request.form.get("email", "").strip()
      raw_amounts = request.form.get("amounts", "").strip()
      currency = request.form.get("currency", "USD").strip().upper() or "USD"
      subject = request.form.get("subject", "You have money!").strip() or "You have money!"
      message = request.form.get("message", "You received a payment. Thanks for using our service!").strip() or "You received a payment. Thanks for using our service!"

      if not email:
        flash("Recipient email is required", "error")
        return redirect(url_for("index"))

      amounts = parse_amounts(raw_amounts)

      payout_body = build_payout_body(email, amounts, currency, subject, message)
      token = mass.get_access_token(client_id, client_secret)
      result = mass.create_payout(token, payout_body, prefer_async=True)
      batch_id = mass._extract_batch_id(result)

      if not batch_id:
        flash("Payout created but no batch id returned", "warning")
        return render_template("result.html", result_json=json.dumps(result, indent=2), batch_id=None)

      return redirect(url_for("payout_status", batch_id=batch_id))
    except Exception as error:
      flash(str(error), "error")
      return redirect(url_for("index"))

  @app.get("/status/<batch_id>")
  def payout_status(batch_id: str):
    try:
      client_id = session.get("paypal_client_id") or os.environ.get("PAYPAL_CLIENT_ID")
      client_secret = session.get("paypal_client_secret") or os.environ.get("PAYPAL_CLIENT_SECRET")
      if not client_id or not client_secret:
        return "Missing PAYPAL_CLIENT_ID or PAYPAL_CLIENT_SECRET in environment", 500
      token = mass.get_access_token(client_id, client_secret)
      status = mass.get_payout_status(token, batch_id)
      return render_template("status.html", batch_id=batch_id, status=status)
    except Exception as error:
      return str(error), 500

  return app


if __name__ == "__main__":
  app = create_app()
  app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)), debug=True)


