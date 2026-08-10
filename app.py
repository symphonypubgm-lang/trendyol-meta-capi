import os
import time
import hashlib
import requests
from flask import Flask, request, jsonify

app = Flask(__name__)

# =========================
# META
# =========================
META_PIXEL_ID = os.environ.get("META_PIXEL_ID")
META_ACCESS_TOKEN = os.environ.get("META_ACCESS_TOKEN")
META_API_VERSION = os.environ.get("META_API_VERSION", "v24.0")
# =========================
# TIKTOK
# =========================

TIKTOK_ACCESS_TOKEN = os.environ.get("TIKTOK_ACCESS_TOKEN")
TIKTOK_EVENT_SET_ID = os.environ.get("TIKTOK_EVENT_SET_ID")
# =========================
# TRENDYOL
# =========================
TRENDYOL_SUPPLIER_ID = os.environ.get("TRENDYOL_SUPPLIER_ID")
TRENDYOL_API_KEY = os.environ.get("TRENDYOL_API_KEY")
TRENDYOL_API_SECRET = os.environ.get("TRENDYOL_API_SECRET")

# Türkiye hesabında boş bırakabiliriz.
# İleride gerekirse Render Environment'a
# TRENDYOL_STOREFRONT_CODE ekleriz.
TRENDYOL_STOREFRONT_CODE = os.environ.get(
    "TRENDYOL_STOREFRONT_CODE"
)


def sha256(value):
    if not value:
        return None

    return hashlib.sha256(
        str(value).strip().lower().encode("utf-8")
    ).hexdigest()


def meta_send_event(
    event_name,
    event_time,
    event_id,
    user_data,
    custom_data
):
    if not META_PIXEL_ID or not META_ACCESS_TOKEN:
        return {
            "ok": False,
            "error": "Meta ayarları eksik."
        }

    event = {
        "event_name": event_name,
        "event_time": int(event_time),
        "event_id": str(event_id),
        "action_source": "other",
        "user_data": user_data,
        "custom_data": custom_data
    }

    payload = {
        "data": [event]
    }

    url = (
        f"https://graph.facebook.com/"
        f"{META_API_VERSION}/{META_PIXEL_ID}/events"
    )

    try:
        response = requests.post(
            url,
            params={
                "access_token": META_ACCESS_TOKEN
            },
            json=payload,
            timeout=30
        )

        try:
            result = response.json()
        except Exception:
            result = {
                "raw": response.text
            }

        return {
            "ok": response.ok,
            "status": response.status_code,
            "response": result
        }

    except requests.RequestException as e:
        return {
            "ok": False,
            "error": str(e)
        }


def trendyol_headers():
    headers = {
        "User-Agent": (
            f"{TRENDYOL_SUPPLIER_ID} "
            "- TrendyolMetaCapi"
        )
    }

    if TRENDYOL_STOREFRONT_CODE:
        headers["storeFrontCode"] = (
            TRENDYOL_STOREFRONT_CODE
        )

    return headers


def get_trendyol_orders(hours=24, status=None):
    if (
        not TRENDYOL_SUPPLIER_ID
        or not TRENDYOL_API_KEY
        or not TRENDYOL_API_SECRET
    ):
        raise Exception(
            "Trendyol API bilgileri eksik."
        )

    now_ms = int(time.time() * 1000)
    start_ms = now_ms - (
        int(hours) * 60 * 60 * 1000
    )

    url = (
        "https://apigw.trendyol.com/"
        "integration/order/sellers/"
        f"{TRENDYOL_SUPPLIER_ID}/orders"
    )

    params = {
        "startDate": start_ms,
        "endDate": now_ms,
        "page": 0,
        "size": 200,
        "orderByField":
            "PackageLastModifiedDate",
        "orderByDirection": "DESC"
    }

    if status:
        params["status"] = status

    response = requests.get(
        url,
        params=params,
        headers=trendyol_headers(),
        auth=(
            TRENDYOL_API_KEY,
            TRENDYOL_API_SECRET
        ),
        timeout=30
    )

    if not response.ok:
        raise Exception(
            f"Trendyol API hata "
            f"{response.status_code}: "
            f"{response.text}"
        )

    return response.json()


def first_value(data, keys):
    for key in keys:
        value = data.get(key)

        if value not in (
            None,
            "",
            [],
            {}
        ):
            return value

    return None


def build_meta_user_data(order):
    user_data = {}

    address = (
        order.get("shipmentAddress")
        or order.get("invoiceAddress")
        or {}
    )

    customer_email = first_value(
        order,
        [
            "customerEmail",
            "email"
        ]
    )

    phone = first_value(
        address,
        [
            "phone",
            "phoneNumber"
        ]
    )

    first_name = first_value(
        address,
        [
            "firstName",
            "name"
        ]
    )

    last_name = first_value(
        address,
        [
            "lastName",
            "surname"
        ]
    )

    city = first_value(
        address,
        [
            "city",
            "cityName"
        ]
    )

    external_id = first_value(
        order,
        [
            "customerId",
            "orderNumber",
            "id"
        ]
    )

    if customer_email:
        user_data["em"] = [
            sha256(customer_email)
        ]

    if phone:
        cleaned_phone = (
            str(phone)
            .replace(" ", "")
            .replace("-", "")
            .replace("(", "")
            .replace(")", "")
        )

        user_data["ph"] = [
            sha256(cleaned_phone)
        ]

    if first_name:
        user_data["fn"] = [
            sha256(first_name)
        ]

    if last_name:
        user_data["ln"] = [
            sha256(last_name)
        ]

    if city:
        user_data["ct"] = [
            sha256(city)
        ]

    user_data["country"] = [
        sha256("tr")
    ]

    if external_id:
        user_data["external_id"] = [
            sha256(external_id)
        ]

    return user_data


def get_order_value(order):
    possible_fields = [
        "grossAmount",
        "totalPrice",
        "packageTotalPrice",
        "totalAmount"
    ]

    for field in possible_fields:
        value = order.get(field)

        if value is not None:
            try:
                return float(value)
            except Exception:
                pass

    lines = order.get("lines") or []

    total = 0.0

    for line in lines:
        price = (
            line.get("price")
            or line.get("amount")
            or 0
        )

        quantity = (
            line.get("quantity")
            or 1
        )

        try:
            total += (
                float(price)
                * float(quantity)
            )
        except Exception:
            pass

    return round(total, 2)


def get_order_event_time(order):
    value = (
        order.get("orderDate")
        or order.get("createdDate")
        or order.get(
            "packageLastModifiedDate"
        )
    )

    if not value:
        return int(time.time())

    try:
        number = int(value)

        # Trendyol tarihleri genellikle
        # milisaniye timestamp.
        if number > 100000000000:
            return int(number / 1000)

        return number

    except Exception:
        return int(time.time())


@app.route("/", methods=["GET"])
def home():
    return jsonify({
        "status": "ok",
        "service": "trendyol-meta-capi",
        "trendyol_configured": bool(
            TRENDYOL_SUPPLIER_ID
            and TRENDYOL_API_KEY
            and TRENDYOL_API_SECRET
        ),
        "meta_configured": bool(
            META_PIXEL_ID
            and META_ACCESS_TOKEN
        )
    })


@app.route("/health", methods=["GET"])
def health():
    return jsonify({
        "status": "healthy"
    })


# =========================
# ESKİ /EVENT ENDPOINT
# =========================
@app.route("/event", methods=["POST"])
def send_event():
    if not META_PIXEL_ID or not META_ACCESS_TOKEN:
        return jsonify({
            "error":
                "META_PIXEL_ID veya "
                "META_ACCESS_TOKEN eksik."
        }), 500

    body = request.get_json(
        silent=True
    ) or {}

    event_name = body.get(
        "event_name",
        "Purchase"
    )

    event_time = body.get(
        "event_time",
        int(time.time())
    )

    event_id = (
        body.get("event_id")
        or f"manual-{int(time.time())}"
    )

    user = body.get("user", {})
    custom_data = body.get(
        "custom_data",
        {}
    )

    user_data = {}

    if user.get("email"):
        user_data["em"] = [
            sha256(user["email"])
        ]

    if user.get("phone"):
        user_data["ph"] = [
            sha256(user["phone"])
        ]

    if user.get("first_name"):
        user_data["fn"] = [
            sha256(user["first_name"])
        ]

    if user.get("last_name"):
        user_data["ln"] = [
            sha256(user["last_name"])
        ]

    if user.get("city"):
        user_data["ct"] = [
            sha256(user["city"])
        ]

    if user.get("country"):
        user_data["country"] = [
            sha256(user["country"])
        ]

    if user.get("external_id"):
        user_data["external_id"] = [
            sha256(user["external_id"])
        ]

    result = meta_send_event(
        event_name=event_name,
        event_time=event_time,
        event_id=event_id,
        user_data=user_data,
        custom_data=custom_data
    )

    status_code = (
        result.get("status", 200)
        if result.get("ok")
        else result.get("status", 502)
    )

    return jsonify(result), status_code


# =========================
# TRENDYOL SİPARİŞLERİNİ GÖR
# =========================
@app.route(
    "/trendyol/orders",
    methods=["GET"]
)
def trendyol_orders():
    hours = request.args.get(
        "hours",
        24,
        type=int
    )

    status = request.args.get("status")

    try:
        data = get_trendyol_orders(
            hours=hours,
            status=status
        )

        content = data.get(
            "content",
            []
        )

        # Kişisel verileri burada
        # gereksiz yere göstermiyoruz.
        summary = []

        for order in content:
            summary.append({
                "id": order.get("id"),
                "orderNumber":
                    order.get("orderNumber"),
                "status":
                    order.get("status"),
                "orderDate":
                    order.get("orderDate"),
                "value":
                    get_order_value(order)
            })

        return jsonify({
            "count": len(summary),
            "orders": summary
        })

    except Exception as e:
        return jsonify({
            "error": str(e)
        }), 502


# =========================
# GERÇEK SİPARİŞLERİ META'YA GÖNDER
# =========================
@app.route("/sync", methods=["POST"])
def sync_orders():
    body = request.get_json(
        silent=True
    ) or {}

    hours = int(
        body.get("hours", 24)
    )

    status = body.get("status")

    try:
        data = get_trendyol_orders(
            hours=hours,
            status=status
        )

        orders = data.get(
            "content",
            []
        )

        results = []

        for order in orders:
            order_number = (
                order.get("orderNumber")
                or order.get("id")
            )

            package_id = order.get("id")

            # Aynı sipariş tekrar çekilse bile
            # aynı event_id kullanılacak.
            event_id = (
                f"trendyol-purchase-"
                f"{order_number}-"
                f"{package_id}"
            )

            user_data = (
                build_meta_user_data(order)
            )

            value = get_order_value(order)

            custom_data = {
                "currency": "TRY",
                "value": value
            }

            lines = order.get("lines") or []

            content_ids = []

            contents = []

            for line in lines:
                barcode = (
                    line.get("barcode")
                    or line.get(
                        "merchantSku"
                    )
                    or line.get(
                        "productCode"
                    )
                )

                quantity = (
                    line.get("quantity")
                    or 1
                )

                price = (
                    line.get("price")
                    or 0
                )

                if barcode:
                    content_ids.append(
                        str(barcode)
                    )

                    contents.append({
                        "id": str(barcode),
                        "quantity":
                            int(quantity),
                        "item_price":
                            float(price)
                    })

            if content_ids:
                custom_data[
                    "content_ids"
                ] = content_ids

                custom_data[
                    "content_type"
                ] = "product"

                custom_data[
                    "contents"
                ] = contents

            result = meta_send_event(
                event_name="Purchase",
                event_time=(
                    get_order_event_time(
                        order
                    )
                ),
                event_id=event_id,
                user_data=user_data,
                custom_data=custom_data
 )
            tiktok_result = tiktok_send_purchase(
            order=order,
            event_id=event_id,
            value=value
)
            results.append({
                "orderNumber":
                    order_number,
                "packageId":
                    package_id,
                "value": value,
                "meta": result,
                "tiktok": tiktok_result
            })

        return jsonify({
            "orders_found": len(orders),
            "results": results
        })

    except Exception as e:
        return jsonify({
            "error": str(e)
        }), 502

def tiktok_send_purchase(order, event_id, value):
    if not TIKTOK_ACCESS_TOKEN or not TIKTOK_EVENT_SET_ID:
        return {"ok": False, "error": "TikTok bilgileri eksik"}

    user = build_meta_user_data(order)

    tiktok_user = {}

    if user.get("em"):
        tiktok_user["emails"] = user["em"]

    if user.get("ph"):
        tiktok_user["phone_numbers"] = user["ph"]

    payload = {
        "event_set_id": TIKTOK_EVENT_SET_ID,
        "test_event_code": "TEST19521",
        "event": "Purchase",
        "event_id": str(event_id),
        "timestamp": time.strftime(
            "%Y-%m-%dT%H:%M:%SZ",
            time.gmtime()
        ),
        "context": {
            "user": tiktok_user
        },
        "properties": {
            "order_id": str(
                order.get("orderNumber")
                or order.get("id")
            ),
            "currency": "TRY",
            "value": float(value),
            "event_channel": "other"
        }
    }

    r = requests.post(
        "https://business-api.tiktok.com/open_api/v1.3/offline/track/",
        headers={
            "Access-Token": TIKTOK_ACCESS_TOKEN,
            "Content-Type": "application/json"
        },
        json=payload,
        timeout=20
    )

    try:
        response_data = r.json()
    except Exception:
        response_data = {"text": r.text}

    return {
        "ok": r.status_code == 200 and response_data.get("code") == 0,
        "status": r.status_code,
        "response": response_data
    }
if __name__ == "__main__":
    port = int(
        os.environ.get(
            "PORT",
            10000
        )
    )

    app.run(
        host="0.0.0.0",
        port=port
    )
