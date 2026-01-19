from django.shortcuts import render
import stripe
import json
from django.conf import settings
from django.http import JsonResponse, HttpResponse
from django.views.decorators.csrf import csrf_exempt
from rest_framework.decorators import api_view
from django.core.mail import send_mail

from auto_parts_app.models import Product, Order, OrderItem 
from auto_parts_app.utils import get_conversion_rate
from decimal import Decimal, ROUND_HALF_UP

from payments.views_shipping import (
    calculate_shipping_price,
    create_sendparcel_shipment,   
)

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
        address = data.get("address", {})
        currency = data.get("currency", "eur").lower()  # for Stripe
        conversion_currency = currency.upper()          # for Frankfurter

        logger.info("Cart received: %s", cart)
        logger.info("Address received: %s", address)

        if not cart:
            return JsonResponse({"error": "Cart is empty"}, status=400)
    
        # Validate address
        country = address.get("country")
        city = address.get("city")
        postal_code = address.get("postal_code")

        if not country or not city or not postal_code:
            logger.error("Missing shipping address: %s", address)
            return JsonResponse({"error": "Missing shipping address"}, status=400)
        
        # Ensure API keys exist
        if not SENDPARCEL_API_KEY:
            logger.error("SENDPARCEL_API_KEY not configured")
            return JsonResponse({"error": "Shipping configuration missing"}, status=502)
        
        if not STRIPE_KEY:
            logger.error("STRIPE_SECRET_KEY missing")
            return JsonResponse({"error": "Stripe not configured"}, status=502)
        
        # Get conversion rate (Frankfurter)
        rate = get_conversion_rate(conversion_currency)
        rate_dec = Decimal(str(rate)) # conversion rate as Decimal

        # Calculate parcel dimensions, weight for SendParcel
        total_weight = Decimal("0")
        max_length = Decimal("0")
        max_width = Decimal("0")
        max_height = Decimal("0")
        total_value_eur = Decimal("0")

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

            total_value_eur += Decimal(str(product.price)) * qty

        # Get shipping price + product_id from SendParcel
        try:
            shipping_quote = calculate_shipping_price(
                country=country,
                city=city,
                postal_code=postal_code,
                weight=total_weight,
                length=max_length,
                width=max_width,
                height=max_height,
                value_eur=float(total_value_eur),
            )
            shipping_price_eur = shipping_quote["amount"]
            sendparcel_product_id = shipping_quote["product_id"]
        except Exception as exc:
            logger.exception("SendParcel failed")
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

            base_price = product.sale_price if product.on_sale else product.price
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
        shipping_cents = int(
            (shipping_dec * rate_dec * Decimal("100")).to_integral_value(rounding=ROUND_HALF_UP)
        )

        line_items.append({
            "price_data": {
                "currency": currency,
                "product_data": {"name": "Shipping"},
                "unit_amount": shipping_cents,
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

        # Create Stripe checkout session
        session = stripe.checkout.Session.create(
            payment_method_types=["card"],
            line_items=line_items,
            mode="payment",
            success_url="https://gearpro01e.com/?payment=success",
            cancel_url="https://gearpro01e.com/?payment=failed",
            phone_number_collection={"enabled": True},
            metadata={
                "cart": json.dumps(metadata_cart),
                "shipping_address": json.dumps(address),  # store frontend address
                "shipping_price": str(shipping_dec),      # store fixed shipping price
                "goods_value_eur": str(total_value_eur),       # total goods value in EUR
                "sendparcel_product_id": str(sendparcel_product_id),
            }
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
        if event["type"] == "checkout.session.completed":
            raw_session = event["data"]["object"]

            metadata = raw_session.get("metadata", {}) or {}

            # Cart metadata from create_checkout_session
            try:
                cart = json.loads(metadata.get("cart", "[]"))
            except Exception:
                logger.exception("Failed to get cart metadata")
                cart = []

            # Shipping address metadata from frontend
            try:
                shipping_data = json.loads(metadata.get("shipping_address", "{}"))
            except Exception:
                logger.exception("Failed to get shipping address metadata")
                shipping_data = {}

            try:
                shipping_price = Decimal(metadata.get("shipping_price", "0"))
            except Exception:
                shipping_price = Decimal("0")

            try:
                goods_value_eur = Decimal(metadata.get("goods_value_eur", "0"))
            except Exception:
                goods_value_eur = Decimal("0")

            sendparcel_product_id = metadata.get("sendparcel_product_id")

             # Customer info from Stripe 
            customer_details = raw_session.get("customer_details") or {}
            customer_email = customer_details.get("email") or "unknown@example.com"
            customer_name = customer_details.get("name") or "Unknown"
            customer_phone = customer_details.get("phone") or "N/A"

            total_price = raw_session.get("amount_total", 0) / 100
            currency = raw_session.get("currency", "eur").upper()

            # Shipping address: use ONLY our metadata 
            shipping_address = ", ".join(
                filter(
                    None,
                    [
                        shipping_data.get("street"),
                        shipping_data.get("city"),
                        shipping_data.get("postal_code"),
                        shipping_data.get("country"),
                    ],
                )
            )
            shipping_city = shipping_data.get("city")
            shipping_postal_code = shipping_data.get("postal_code")
            shipping_country = shipping_data.get("country")

            # Create Order in DB
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

            # Emails

            try:
                # Email to customer
                send_mail(
                    subject=f"Order #{order.id} confirmation – GearPro",
                    message=(
                        f"Hi {customer_name},\n\n"
                        f"Thank you for your purchase!\n\n"
                        f"Order ID: {order.id}\n"
                        f"Total: {total_price} {currency}\n\n"
                        f"We will contact you when your order is shipped.\n\n"
                        f"GearPro Team"
                    ),
                    from_email="info@gearpro01e.com", 
                    recipient_list=[customer_email],
                )

                # Email to admin
                send_mail(
                    subject=f"New order #{order.id}",
                    message=(
                        f"New order received\n\n"
                        f"Order ID: {order.id}\n"
                        f"Customer: {customer_name}\n"
                        f"Email: {customer_email}\n"
                        f"Phone: {customer_phone}\n"
                        f"Total: {total_price} {currency}"
                    ),
                    from_email="info@gearpro01e.com",
                    recipient_list=["info@gearpro01e.com"],
                )

            except Exception:
                logger.exception("Failed to send order emails")

            # Create OrderItems in DB and recompute parcels for SendParcel
            from decimal import Decimal as D

            total_weight = D("0")
            max_length = D("0")
            max_width = D("0")
            max_height = D("0")

            for item in cart:
                item_id = item.get("id")
                if item_id == "shipping":
                    continue

                try:
                    product = Product.objects.get(id=item_id)
                except Product.DoesNotExist:
                    logger.warning("Product ID %s not found during webhook", item_id)
                    continue

                quantity = int(item.get("quantity", 1) or 1)
                price_at_purchase = item.get("price", 0)

                OrderItem.objects.create(
                    order=order,
                    product=product,
                    quantity=quantity,
                    price_at_purchase=price_at_purchase,
                )

                # decrement stock
                if hasattr(product, "stock") and product.stock is not None:
                    product.stock = max(0, product.stock - quantity)
                    product.save()

                # accumulate shipping params
                if getattr(product, "weight", None) is not None:
                    total_weight += D(str(product.weight)) * quantity
                if getattr(product, "length", None) is not None:
                    max_length = max(max_length, D(str(product.length)))
                if getattr(product, "width", None) is not None:
                    max_width = max(max_width, D(str(product.width)))
                if getattr(product, "height", None) is not None:
                    max_height = max(max_height, D(str(product.height)))

            # Build parcels list for SendParcel
            parcels = [{
                "weight": float(total_weight or D("0")),
                "length": float(max_length or D("0")),
                "width": float(max_width or D("0")),
                "height": float(max_height or D("0")),
            }]

            # Prepare shipping address dict for SendParcel
            sendparcel_shipping_address = {
                **shipping_data,
                "phone": customer_phone,
                "email": customer_email,
            }

            # Create SendParcel shipment
            try:
                create_sendparcel_shipment(
                    order=order,
                    shipping_address=sendparcel_shipping_address,
                    parcels=parcels,
                    total_value_eur=goods_value_eur,
                    product_id=sendparcel_product_id,
                )
            except Exception:
                # Don't fail webhook if SendParcel fails – just log
                logger.exception("Failed to create SendParcel shipment for order %s", order.id)

    except Exception as e:
        logger.exception("Error processing Stripe webhook: %s", str(e))
        return HttpResponse(status=500)

    return HttpResponse(status=200)