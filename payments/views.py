from django.shortcuts import render
import stripe
import json
from django.conf import settings
from django.http import JsonResponse, HttpResponse
from django.views.decorators.csrf import csrf_exempt
from rest_framework.decorators import api_view

from auto_parts_app.models import Product, Order, OrderItem 
from auto_parts_app.utils import get_conversion_rate
from decimal import Decimal, ROUND_HALF_UP
from payments.views_shipping import calculate_shipping_price

import logging

logger = logging.getLogger(__name__)

SENDPARCEL_API_KEY = getattr(settings, "SENDPARCEL_API_KEY", None)
STRIPE_KEY = getattr(settings, "STRIPE_SECRET_KEY", None)
if STRIPE_KEY:
    stripe.api_key = STRIPE_KEY
else:
    logger.warning("STRIPE_SECRET_KEY not found in settings")

# CREATE STRIPE CHECKOUT SESSION

@csrf_exempt
@api_view(['POST'])
def create_checkout_session(request):
    try:
        data = json.loads(request.body)
        cart = data.get("cart", [])
        currency = data.get("currency", "eur").lower()  # for Stripe
        conversion_currency = currency.upper()          # for Frankfurter

        logger.info("Cart received: %s", cart)

        if not cart:
            return JsonResponse({"error": "Cart is empty"}, status=400)
        
        # Ensure SendParcel key exists
        if not SENDPARCEL_API_KEY:
            logger.error("SENDPARCEL_API_KEY not configured")
            return JsonResponse({"error": "Shipping configuration missing"}, status=502)
        
        # Get conversion rate (Frankfurter)
        rate = get_conversion_rate(conversion_currency)
        rate_dec = Decimal(str(rate)) # conversion rate as Decimal

        # Calculate parcel dimensions, weight for SendParcel
        total_weight = Decimal("0")
        max_length = Decimal("0")
        max_width = Decimal("0")
        max_height = Decimal("0")

        for item in cart:
            item_id = item.get("id")
            qty = int(item.get("quantity", 0) or 0)
            if qty <= 0:
                logger.warning("Invalid quantity for cart item %s: %s", item_id, item.get("quantity"))
                continue
            try:
                product = Product.objects.get(id=item_id)
            except Product.DoesNotExist:
                logger.warning("Product ID %s not found when calculating shipping; skipping", item_id)
                continue

            total_weight += Decimal(str(product.weight)) * qty
            max_length = max(max_length, Decimal(str(product.length)))
            max_width = max(max_width, Decimal(str(product.width)))
            max_height = max(max_height, Decimal(str(product.height)))

        destination_country = data.get("shipping_country", "LT")

         # Get shipping price (handles timeouts and errors)
        try:
            shipping_price_eur = calculate_shipping_price(
                country=destination_country,
                postal_code=data.get("shipping_postal_code", ""),
                weight=total_weight,
                length=max_length,
                width=max_width,
                height=max_height,
                value_eur=0,
            )
        except Exception as exc:
            logger.exception("SendParcel price calculation failed")
            return JsonResponse({"error": "Shipping API error", "detail": str(exc)}, status=502)

        # Stripe line items
        line_items = []
        metadata_cart = []

        for item in cart:
            item_id = item.get("id")
            qty = int(item.get("quantity", 0) or 0)
            if qty <= 0:
                continue
            try:
                product = Product.objects.get(id=item_id)
            except Product.DoesNotExist:
                logger.warning("Product ID %s not found, skipping", item_id)
                continue

            base_price = product.sale_price if getattr(product, "on_sale", False) else product.price
            price_dec = Decimal(str(base_price))

            converted_price_cents = int(
                (price_dec * rate_dec * Decimal("100")).to_integral_value(rounding=ROUND_HALF_UP)
            )

            line_items.append({
                "price_data": {
                    "currency": currency,
                    "product_data": {
                        "name": product.name,
                        "description": product.description or "",
                    },
                    "unit_amount": converted_price_cents,
                },
                "quantity": qty,
            })

            metadata_cart.append({
                "id": item_id,
                "quantity": qty,
                "price": int(
                    (price_dec * rate_dec).to_integral_value(rounding=ROUND_HALF_UP)
                ) # price in requested currency
            })

        if not line_items:
            return JsonResponse({"error": "Cart is empty or invalid"}, status=400)
        
        # Add shipping as a Stripe item
        shipping_dec = Decimal(str(shipping_price_eur))
        converted_shipping_cents = int(
            (shipping_dec * rate_dec * Decimal("100")).to_integral_value(rounding=ROUND_HALF_UP)
        )
        line_items.append({
            "price_data": {
                "currency": currency,
                "product_data": {"name": "Shipping (SendParcel)"},
                "unit_amount": converted_shipping_cents,
            },
            "quantity": 1,
        })
        metadata_cart.append({
            "id": "shipping",
            "quantity": 1,
            "price": int(
                (shipping_dec * rate_dec).to_integral_value(rounding=ROUND_HALF_UP)
            )
        })

        # Ensure stripe API key exists before creating session
        if not getattr(stripe, "api_key", None):
            logger.error("Stripe API key not configured")
            return JsonResponse({"error": "Payment gateway not configured"}, status=502)

        # Create Stripe checkout session
        session = stripe.checkout.Session.create(
            payment_method_types=["card"],
            line_items=line_items,
            mode="payment",
            success_url="https://gearpro01e.com/?payment=success",
            cancel_url="https://gearpro01e.com/?payment=failed",
            shipping_address_collection={
                "allowed_countries": [
                    # Amerika
                    "US", "CA",
                    # EU
                    "AT","BE","BG","HR","CY","CZ","DK","EE","FI","FR","DE","GR","HU","IE",
                    "IT","LV","LT","LU","MT","NL","PL","PT","RO","SK","SI","ES","SE",
                    # Other 
                    "NO","CH","IS", "GB"  
                ],
            },
            phone_number_collection={"enabled": True},
            metadata={"cart": json.dumps(metadata_cart)}
        )

        logger.info("Stripe session created: %s", getattr(session, "id", "unknown"))
        return JsonResponse({"id": session.id})

    except stripe.error.StripeError as e:
        logger.exception("Stripe API error")
        return JsonResponse({"error": str(e)}, status=400)
    
    except Exception as e:
        logger.exception("Error creating checkout session")
        return JsonResponse({"error": str(e)}, status=500)

# webhook to handle successful payments
@csrf_exempt
def stripe_webhook(request):
    payload = request.body
    sig_header = request.META.get('HTTP_STRIPE_SIGNATURE', '')
    endpoint_secret = getattr(settings, "STRIPE_WEBHOOK_SECRET", None)

    if not sig_header or not endpoint_secret:
        logger.error("Missing Stripe signature or webhook secret")
        return HttpResponse(status=400)

    try:
        event = stripe.Webhook.construct_event(payload, sig_header, endpoint_secret)
    except (ValueError, stripe.error.SignatureVerificationError) as e:
        logger.error("Webhook signature verification failed: %s", str(e))
        return HttpResponse(status=400)

    try:
        if event.get["type"] == "checkout.session.completed":
            raw_session = event["data"]["object"]

            # Extract customer info
            customer_details = raw_session.get("customer_details") or {}
            payment_method_details = raw_session.get("payment_method_details") or {}
            billing_details = payment_method_details.get("billing_details") or {}

            customer_email = customer_details.get("email") or billing_details.get("email") or "unknown@example.com"
            customer_name = customer_details.get("name") or billing_details.get("name") or "Unknown"
            customer_phone = (
                customer_details.get("phone") or
                billing_details.get("phone") or
                "N/A"
            )

            total_price = raw_session.get("amount_total", 0) / 100
            currency = raw_session.get("currency", "eur").upper()

            # Shipping
            shipping_info = raw_session.get("shipping_details") or {}
            address = shipping_info.get("address") or customer_details.get("address") or billing_details.get("address") or {}

            shipping_address = ", ".join(filter(None, [address.get("line1"), address.get("line2"), address.get("city")])) 
            shipping_city = address.get("city")
            shipping_postal_code = address.get("postal_code")
            shipping_country = address.get("country")

            # Create the order
            order = Order.objects.create(
                customer_name=customer_name,
                customer_email=customer_email,
                customer_phone=customer_phone,
                total_price=total_price,
                currency=currency,
                status="paid",
                shipping_address=shipping_address,
                shipping_city=shipping_city,
                shipping_postal_code=shipping_postal_code,
                shipping_country=shipping_country,
            )

            # Save items from metadata
            try:
                cart = json.loads(raw_session.get("metadata", {}).get("cart", "[]"))
            except Exception:
                logger.error("Failed to parse cart metadata from stripe session")
                cart = []

            for item in cart:
                item_id = item.get("id")
                try:
                    product = Product.objects.get(id=item_id)
                    quantity = int(item.get("quantity", 1) or 1)
                    price_at_purchase = item.get("price", 0)

                    OrderItem.objects.create(
                        order=order,
                        product=product,
                        quantity=quantity,
                        price_at_purchase=price_at_purchase
                    )

                    # decrement stock 
                    if hasattr(product, "stock") and product.stock is not None:
                        product.stock = max(0, product.stock - quantity)
                        product.save()
                except Product.DoesNotExist:
                    logger.warning("Product ID %s not found during webhook", item_id)

    except Exception as e:
        logger.exception("Error processing Stripe webhook: %s", str(e))
        return HttpResponse(status=500)

    return HttpResponse(status=200)