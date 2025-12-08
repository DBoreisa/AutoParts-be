from django.db import models

class Product(models.Model):
    class Category(models.TextChoices):
        ENIGINE_COMPARTMENT = "engine compartment", "Engine compartment"
        INTERIOR = "interior", "Interior"
        CHASSIS = "chassis", "Chassis"
        TRANSMISSION = "transmission", "Transmission"
        ELECTRONICS = "electronics", "Electronics"
        BRAKE_SYSTEM = "brake system", "Brake system"

    name = models.CharField(max_length=200)
    description = models.TextField(blank=True)
    price = models.DecimalField(max_digits=10, decimal_places=2)
    sale_price = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True) 
    on_sale = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    category = models.CharField(
       max_length=20,
       choices=Category.choices,
       default=Category.TRANSMISSION,
    )
    stock = models.IntegerField(default=0)
    weight = models.DecimalField(max_digits=6, decimal_places=2, help_text="kg", default=0.0)  # kg
    length = models.DecimalField(max_digits=6, decimal_places=2, help_text="cm", default=0.0)  # cm
    width = models.DecimalField(max_digits=6, decimal_places=2, help_text="cm", default=0.0)   # cm
    height = models.DecimalField(max_digits=6, decimal_places=2, help_text="cm", default=0.0)  # cm
    is_active = models.BooleanField(default=True)

    def save(self, *args, **kwargs):
        # atnaujina is_active reiksme pagal stock
        self.is_active = self.stock > 0
        super().save(*args, **kwargs)

    def __str__(self):
        return self.name

class ProductImage(models.Model):
    product = models.ForeignKey(Product, related_name='images', on_delete=models.CASCADE)
    image = models.ImageField(upload_to='products/')

class Order(models.Model):
    STATUS_CHOICES = [
        ("pending", "Pending"),
        ("paid", "Paid"),
        ("shipped", "Shipped"),
        ("completed", "Completed"),
        ("cancelled", "Cancelled"),
    ]
    customer_name = models.CharField(max_length=255)
    customer_email = models.EmailField()
    customer_phone = models.CharField(max_length=30, default="N/A")

    # adreso laukai
    shipping_address = models.CharField(max_length=255, default="N/A")
    shipping_city = models.CharField(max_length=100, default="N/A")
    shipping_postal_code = models.CharField(max_length=20, default="00000")
    shipping_country = models.CharField(max_length=100, default="Unknown")

    shipping_price = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    created_at = models.DateTimeField(auto_now_add=True)
    currency = models.CharField(max_length=10, default="EUR")
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default="pending")
    total_price = models.FloatField()

class OrderItem(models.Model):
    order = models.ForeignKey(Order, on_delete=models.CASCADE, related_name="items")
    product = models.ForeignKey(Product, on_delete=models.PROTECT) 
    quantity = models.IntegerField()
    price_at_purchase = models.FloatField()  # store price at purchase