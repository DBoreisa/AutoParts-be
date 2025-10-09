from django.urls import path
from .views import ProductView
from .views import ProductView, categories
from . import views

urlpatterns = [
	path('', ProductView.as_view(), name='product-root'),
    path('products/', ProductView.as_view(), name='product-list'),
    path('categories/', categories, name='categories'),
]