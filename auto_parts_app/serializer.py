from rest_framework import serializers
from .models import *

class ProductImageSerializer(serializers.ModelSerializer):
    image = serializers.SerializerMethodField()

    def get_image(self, obj):
        request = self.context.get('request')
        return request.build_absolute_uri(obj.image.url)

    class Meta:
        model = ProductImage
        fields = ['image']

class ProductSerializer(serializers.ModelSerializer):
    images = ProductImageSerializer(many=True, read_only=True)

    class Meta:
        model = Product
        fields = ['id', 
                  'name', 
                  'description', 
                  'price', 
                  'category', 
                  'images', 
                  'created_at', 
                  'sale_price', 
                  'on_sale', 
                  'stock',
                  'is_active']
