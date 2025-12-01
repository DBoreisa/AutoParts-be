from django.shortcuts import render
import stripe
import json
from django.conf import settings
from django.http import JsonResponse, HttpResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST
from rest_framework.decorators import api_view

from auto_parts_app.models import Product
from auto_parts_app.models import Order, OrderItem 
from auto_parts_app.utils import get_conversion_rate
from decimal import Decimal, ROUND_HALF_UP

import logging

# STRIPE

# checkout session endpoint

logger = logging.getLogger(__name__)
stripe.api_key = settings.STRIPE_SECRET_KEY

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
        
        rate = get_conversion_rate(conversion_currency)

        line_items = []
        metadata_cart = []

        for item in cart:
            try:
                product = Product.objects.get(id=item["id"])
            except Product.DoesNotExist:
                logger.warning("Product ID %s not found, skipping", item.get("id"))
                continue  # skip invalid product

            base_price = product.sale_price if product.on_sale else product.price
            converted_price = int((base_price * Decimal(rate) * 100).to_integral_value(rounding=ROUND_HALF_UP))

            line_items.append({
                "price_data": {
                    "currency": currency,
                    "product_data": {
                        "name": product.name,
                        "description": product.description,
                    },
                    "unit_amount": converted_price,
                },
                "quantity": item["quantity"],
            })

            # metadata price in selected currency (no cents)
            metadata_cart.append({
                "id": item["id"],
                "quantity": item["quantity"],
                "price": int((base_price * Decimal(rate)).to_integral_value(rounding=ROUND_HALF_UP))
            })

        if not line_items:
            return JsonResponse({"error": "Cart is empty or invalid"}, status=400)

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
            phone_number_collection={
                "enabled": True,  
            },
            metadata={"cart": json.dumps(metadata_cart)}
        )

        logger.info("Stripe session created: %s", session.id)
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
    endpoint_secret = settings.STRIPE_WEBHOOK_SECRET

    if not sig_header:
        logger.error("Missing Stripe signature header")
        return HttpResponse(status=400)

    try:
        event = stripe.Webhook.construct_event(payload, sig_header, endpoint_secret)
    except (ValueError, stripe.error.SignatureVerificationError) as e:
        logger.error("Webhook signature verification failed: %s", str(e))
        return HttpResponse(status=400)

    try:
        if event["type"] == "checkout.session.completed":
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

            shipping_address = ", ".join(filter(None, [address.get("line1"), address.get("line2"), address.get("city")])) or "N/A"
            shipping_city = address.get("city", "N/A")
            shipping_postal_code = address.get("postal_code", "00000")
            shipping_country = address.get("country", "Unknown")

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
            except Exception as e:
                logger.error("Failed to parse cart metadata: %s", str(e))
                cart = []

            for item in cart:
                try:
                    product = Product.objects.get(id=item["id"])
                    quantity = item.get("quantity", 1)
                    price_at_purchase = item.get("price", 0)

                    OrderItem.objects.create(
                        order=order,
                        product=product,
                        quantity=quantity,
                        price_at_purchase=price_at_purchase
                    )

                    product.stock -= quantity
                    product.save()
                except Product.DoesNotExist:
                    logger.warning("Product ID %s not found during webhook", item.get("id"))

    except Exception as e:
        logger.exception("Error processing Stripe webhook: %s", str(e))
        return HttpResponse(status=500)

    return HttpResponse(status=200)