from django.shortcuts import render
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.decorators import api_view
from .models import *
from .serializer import *
from django.db.models import Q

class ProductView(APIView):
    def get(self, request):
        # Sorting
        sort_by = request.GET.get("sort", "Date")
        sort_mapping = {
            "Date": "-created_at",
            "Alphabetical": "name",
            "RevAlphabetical": "-name",    
            "Price": "price",
            "RevPrice": "-price"
        }
        ordering = sort_mapping.get(sort_by, "-created_at")

        # Base queryset
        queryset = Product.objects.all()

        # Only active products (in stock)
        in_stock = request.GET.get("in_stock")
        is_active = request.GET.get("is_active")

        if (in_stock and in_stock.lower() == "true") or (is_active and is_active.lower() == "true"):
            queryset = queryset.filter(is_active=True)

        # Search
        search_query = request.GET.get("search")
        if search_query:
            queryset = queryset.filter(name__icontains=search_query)

        # Price filter
        min_price = request.GET.get("min_price")
        max_price = request.GET.get("max_price")
        if min_price and max_price:
            queryset = queryset.filter(price__gte=min_price, price__lte=max_price)
        elif min_price:
            queryset = queryset.filter(price__gte=min_price)
        elif max_price:
            queryset = queryset.filter(price__lte=max_price)

        # Categories filter
        categories = request.GET.getlist("categories") 
        if categories:
            q = Q()
            for cat in categories:
                q |= Q(category__iexact=cat)
            queryset = queryset.filter(q)

        # On-sale filter
        on_sale = request.GET.get("on_sale")
        if on_sale is not None:
            if on_sale.lower() == "true":
                queryset = queryset.filter(on_sale=True)
            elif on_sale.lower() == "false":
                queryset = queryset.filter(on_sale=False)

        products = queryset.order_by(ordering)
        serializer = ProductSerializer(products, many=True, context={"request": request})
        return Response(serializer.data)
    
    def post(self,request):
        serializer = ProductSerializer(data=request.data)
        if serializer.is_valid(raise_exception=True):
            serializer.save()
            return Response(serializer.data)

@api_view(['GET'])
def categories(request):
    # Return a list of category values
    categories = [
        {"value": choice[0], "label": choice[1]}
        for choice in Product.Category.choices
    ]
    return Response(categories)


