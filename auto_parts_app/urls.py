from django.urls import path
from .views import ProductView
from .views import ProductView, categories
from . import views
from payments.views_shipping import get_shipping_quote

urlpatterns = [
	path('', ProductView.as_view(), name='product-root'),
    path('products/', ProductView.as_view(), name='product-list'),
    path('categories/', categories, name='categories'),
    path("shipping/calc/", get_shipping_quote, name="shipping-calc"),
]