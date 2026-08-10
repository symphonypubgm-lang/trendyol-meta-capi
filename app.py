import os
import time
import hashlib
import requests
from flask import Flask, request, jsonify

app = Flask(__name__)

META_PIXEL_ID = os.environ.get("META_PIXEL_ID")
META_ACCESS_TOKEN = os.environ.get("META_ACCESS_TOKEN")
META_API_VERSION = os.environ.get("META_API_VERSION", "v24.0")


def sha256(value):
    if not value:
        return None
    return hashlib.sha256(
        str(value).strip().lower().encode("utf-8")
    ).hexdigest()


@app.route("/", methods=["GET"])
def home():
    return jsonify({
        "status": "ok",
        "service": "trendyol-meta-capi"
    })


@app.route("/health", methods=["GET"])
def health():
    return jsonify({"status": "healthy"})


@app.route("/event", methods=["POST"])
def send_event():
    if not META_PIXEL_ID or not META_ACCESS_TOKEN:
        return jsonify({
            "error": "META_PIXEL_ID veya META_ACCESS_TOKEN eksik."
        }), 500

    body = request.get_json(silent=True) or {}

    event_name = body.get("event_name", "Purchase")
    event_time = body.get("event_time", int(time.time()))
    event_id = body.get("event_id")

    user = body.get("user", {})
    custom_data = body.get("custom_data", {})

    user_data = {}

    if user.get("email"):
        user_data["em"] = [sha256(user["email"])]

    if user.get("phone"):
        user_data["ph"] = [sha256(user["phone"])]

    if user.get("first_name"):
        user_data["fn"] = [sha256(user["first_name"])]

    if user.get("last_name"):
        user_data["ln"] = [sha256(user["last_name"])]

    if user.get("city"):
        user_data["ct"] = [sha256(user["city"])]

    if user.get("country"):
        user_data["country"] = [sha256(user["country"])]

    if user.get("external_id"):
        user_data["external_id"] = [sha256(user["external_id"])]

    event = {
        "event_name": event_name,
        "event_time": event_time,
        "action_source": "website",
        "user_data": user_data
    }

    if event_id:
        event["event_id"] = str(event_id)

    if body.get("event_source_url"):
        event["event_source_url"] = body["event_source_url"]

    if custom_data:
        event["custom_data"] = custom_data

    payload = {"data": [event]}

    if body.get("test_event_code"):
        payload["test_event_code"] = body["test_event_code"]

    url = (
        f"https://graph.facebook.com/"
        f"{META_API_VERSION}/{META_PIXEL_ID}/events"
    )

    try:
        response = requests.post(
            url,
            params={"access_token": META_ACCESS_TOKEN},
            json=payload,
            timeout=20
        )

        return jsonify({
            "meta_status": response.status_code,
            "meta_response": response.json()
        }), response.status_code

    except requests.RequestException as e:
        return jsonify({"error": str(e)}), 502


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)
