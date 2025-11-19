from django.contrib import admin
from django.utils.html import format_html
from .models import Product, ProductImage, Order, OrderItem

# Inline for Product form
class ProductImageInline(admin.TabularInline):
    model = ProductImage
    extra = 1
    readonly_fields = ("image_preview",)

    def image_preview(self, obj):
        if obj.image:
            return format_html('<img src="{}" style="height: 100px;"/>', obj.image.url)
        return "-"
    image_preview.short_description = "Preview"

@admin.register(Product)
class ProductAdmin(admin.ModelAdmin):
    list_display = ("id", "name", "category", "price", "sale_price", "on_sale", "stock", "created_at")
    list_filter = ("category", "created_at", "on_sale")
    search_fields = ("name", "description")
    list_editable = ("on_sale", "sale_price", "stock") 
    ordering = ("-created_at",)
    inlines = [ProductImageInline]

@admin.register(ProductImage)
class ProductImageAdmin(admin.ModelAdmin):
    list_display = ("id", "product", "image_preview")
    readonly_fields = ("image_preview",)

    def image_preview(self, obj):
        if obj.image:
            return format_html('<img src="{}" style="height: 100px;"/>', obj.image.url)
        return "-"
    image_preview.short_description = "Preview"

# Inline for OrderItems inside Order
class OrderItemInline(admin.TabularInline):
    model = OrderItem
    extra = 0
    readonly_fields = ("product", "quantity", "price_at_purchase")
    can_delete = False


@admin.register(Order)
class OrderAdmin(admin.ModelAdmin):
    list_display = ("id", "customer_name", "customer_email", "status", "total_price", "created_at")
    list_filter = ("status", "created_at")
    search_fields = ("customer_name", "customer_email", "id")
    ordering = ("-created_at",)
    inlines = [OrderItemInline]
    list_editable = ["status"] 

    fieldsets = (
        ("Customer Info", {
            "fields": ("customer_name", "customer_email", "customer_phone")
        }),
        ("Shipping Info", {
            "fields": (
                "shipping_address",
                "shipping_city",
                "shipping_postal_code",
                "shipping_country",
            )
        }),
        ("Order Details", {
            "fields": ("status", "total_price", "currency", "created_at")
        }),
    )
    readonly_fields = ("created_at", "total_price")

    # --- Custom action ---
    actions = ["mark_as_shipped"]

    def mark_as_shipped(self, request, queryset):
        updated = queryset.update(status="shipped")
        self.message_user(request, f"{updated} order(s) marked as shipped.")
    mark_as_shipped.short_description = "Mark selected orders as Shipped"


@admin.register(OrderItem)
class OrderItemAdmin(admin.ModelAdmin):
    list_display = ("id", "order", "product", "quantity", "price_at_purchase")
    search_fields = ("order__customer_name", "order__customer_email", "product__name")
    list_filter = ("order__status",)


