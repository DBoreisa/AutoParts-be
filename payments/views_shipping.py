import json
import logging
import requests
from decimal import Decimal
from django.conf import settings
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from rest_framework.decorators import api_view

from auto_parts_app.models import Product

logger = logging.getLogger("payments")

SENDPARCEL_API_KEY = getattr(settings, "SENDPARCEL_API_KEY", None)
SENDPARCEL_BASE_URL = getattr(settings, "SENDPARCEL_BASE_URL", "https://sf6-api.sendparcel.com/rest-api") 

def calculate_shipping_price(country, city, postal_code, weight, length, width, height, value_eur=0):
    """
    Calls SendParcel /quotes endpoint and returns the cheapest shipping price (EUR).
    Raises Exception on failure.
    """
    if not SENDPARCEL_API_KEY:
        raise Exception("SendParcel API key not configured")
    
    url = f"{SENDPARCEL_BASE_URL}/quotes"

    payload = {
        "quote": {
            "packageType": "c_deze",
            "value": float(value_eur or 0),
            "shipper": {
                "is_a_company": getattr(settings, "SENDER_IS_COMPANY", False),
                "country": getattr(settings, "SENDER_COUNTRY", "LT"),
                "postal_code": getattr(settings, "SENDER_POSTAL_CODE", "59136"),
                "city": getattr(settings, "SENDER_CITY", "Prienai"),
            },
            "recipient": {
                "is_a_company": False,
                "country": country,  # ISO code
                "postal_code": postal_code or "",
                "city": city or "unknown",
            },
            "parcels": [
                {
                    "weight": float(weight or 0),
                    "length": float(length or 0),
                    "width": float(width or 0),
                    "height": float(height or 0)
                }
            ]
        }
    }

    headers = {
        "Content-Type": "application/json",
        "Accept": "application/json",
        "password": SENDPARCEL_API_KEY,
    }
    
    try:
        logger.debug("SendParcel payload: %s", json.dumps(payload))
        resp = requests.post(url, json=payload, headers=headers, timeout=(5, 15)) # 5s connect 20s read
        resp.raise_for_status()
    except requests.exceptions.Timeout:
        logger.exception("SendParcel request timed out")
        raise Exception("Shipping provider timed out")
    except requests.exceptions.RequestException as exc:
        logger.exception("SendParcel request failed: %s", exc)
        raise Exception(f"Shipping provider error: {exc}")
    
    try:
        data = resp.json()
    except ValueError:
        logger.error("SendParcel returned non-JSON response: %s", resp.text[:200])
        raise Exception("Shipping provider returned invalid response")
    
    # Take first offer as cheapest
    offers = data.get("offers")
    if not offers or not isinstance(offers, list):
        logger.error("SendParcel response missing 'offers': %s", data)
        raise Exception("No shipping offers returned by SendParcel")

    price_info = offers[0].get("price", {})
    amount = price_info.get("amount")
    if amount is None:
        logger.error("SendParcel offer missing price: %s", offers[0])
        raise Exception("Invalid price from SendParcel")

    return Decimal(str(amount))

@csrf_exempt
@api_view(['POST'])
def get_shipping_quote(request):
    """
    Called from React BEFORE creating Stripe session.
    Calculates total package dimensions + calls SendParcel API.
    """
    try:
        data = json.loads(request.body)
        cart = data.get("cart", [])
        address = data.get("address", {})

        if not cart:
            return JsonResponse({"error": "Missing cart"}, status=400)
        if not address:
            return JsonResponse({"error": "Missing address"}, status=400)

        # Calculate package totals
        total_weight = Decimal("0")
        max_length = Decimal("0")
        max_width = Decimal("0")
        max_height = Decimal("0")

        for item in cart:
            item_id = item.get("id")
            qty = int(item.get("quantity", 0) or 0)
            if qty <= 0:
                continue
            try:
                product = Product.objects.get(id=item_id)
            except Product.DoesNotExist:
                logger.warning("Product id=%s not found when calculating shipping; skipping", item_id)
                continue

            total_weight += Decimal(str(product.weight)) * qty
            max_length = max(max_length, Decimal(str(product.length)))
            max_width = max(max_width, Decimal(str(product.width)))
            max_height = max(max_height, Decimal(str(product.height)))

        try:
            shipping_price = calculate_shipping_price(
                country=address.get("country"),
                city=address.get("city"),
                postal_code=address.get("postal_code", ""),
                weight=total_weight,
                length=max_length,
                width=max_width,
                height=max_height,
                value_eur=data.get("value_eur", 0),
            )
        except Exception as exc:
            logger.exception("Failed to calculate shipping price")
            return JsonResponse({"error": "Shipping provider error", "detail": str(exc)}, status=502)

        return JsonResponse({"shipping_price": shipping_price})
    except Exception as e:
        logger.exception("Error in get_shipping_quote")
        return JsonResponse({"error": str(e)}, status=500)

        
