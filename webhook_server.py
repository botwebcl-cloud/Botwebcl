"""
webhook_server.py
Servidor web pequeño que recibe el aviso automático de MercadoPago cuando
alguien completa un pago, y activa el Premium del usuario correspondiente.

Corre en paralelo al bot de Telegram, dentro del mismo proceso (ver main.py).

Seguridad: en vez de solo confiar en el aviso recibido, el servidor vuelve
a consultar el pago directamente contra la API de MercadoPago usando el
Access Token, para confirmar que el pago es real y fue aprobado.
"""
import os
import logging
import requests
from flask import Flask, request

import database as db

logger = logging.getLogger(__name__)

MP_ACCESS_TOKEN = os.environ.get("MP_ACCESS_TOKEN", "")
PORT = int(os.environ.get("PORT", "8080"))

flask_app = Flask(__name__)


def _verify_and_get_payment(payment_id: str):
    """Consulta el pago directamente en la API de MercadoPago para confirmar
    que es real y está aprobado. Devuelve el JSON del pago o None."""
    url = f"https://api.mercadopago.com/v1/payments/{payment_id}"
    headers = {"Authorization": f"Bearer {MP_ACCESS_TOKEN}"}
    try:
        resp = requests.get(url, headers=headers, timeout=10)
        if resp.status_code != 200:
            logger.warning("No se pudo verificar el pago %s: %s", payment_id, resp.text)
            return None
        return resp.json()
    except requests.RequestException as e:
        logger.error("Error consultando la API de MercadoPago: %s", e)
        return None


@flask_app.route("/mercadopago-webhook", methods=["POST", "GET"])
def mercadopago_webhook():
    # MercadoPago manda el aviso con el id del pago, ya sea en query params
    # (formato clásico) o en el body JSON (formato nuevo de webhooks).
    payment_id = request.args.get("data.id") or request.args.get("id")

    if not payment_id and request.is_json:
        body = request.get_json(silent=True) or {}
        payment_id = (body.get("data") or {}).get("id")

    topic = request.args.get("type") or request.args.get("topic")

    if not payment_id:
        # Puede ser una notificación de otro tipo (ej. "merchant_order"), la ignoramos.
        return "OK", 200

    if not MP_ACCESS_TOKEN:
        logger.error("Falta MP_ACCESS_TOKEN, no se puede verificar el pago.")
        return "Server misconfigured", 500

    payment = _verify_and_get_payment(payment_id)
    if not payment:
        return "OK", 200 # respondemos 200 igual para que MP no reintente infinito

    status = payment.get("status")
    code = payment.get("external_reference")

    if status == "approved" and code:
        user_id = db.redeem_activation_code(code)
        if user_id:
            logger.info("Premium activado automáticamente para user_id=%s", user_id)
        else:
            logger.warning("Código de activación no encontrado o ya usado: %s", code)
    else:
        logger.info("Pago %s con estado '%s', no se activa nada.", payment_id, status)

    return "OK", 200


@flask_app.route("/health", methods=["GET"])
def health():
    return "OK", 200


def run_webhook_server():
    flask_app.run(host="0.0.0.0", port=PORT)
