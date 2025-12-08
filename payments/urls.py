from django.urls import path
from .views import create_checkout_session, stripe_webhook
from .views_shipping import get_shipping_quote

urlpatterns = [
    path("create-checkout-session/", create_checkout_session, name="create-checkout-session"),
    path("stripe-webhook/", stripe_webhook, name="stripe-webhook"),
]