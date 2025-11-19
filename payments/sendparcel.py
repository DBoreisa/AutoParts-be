import requests
import json

SP_API_KEY = "YOUR_API_KEY"
SP_BASE_URL = "https://api.sendparcel.com/rest-api"     # or your SP endpoint

def get_sp_shipping_price(weight, length, width, height, country_code):
    url = f"{SP_BASE_URL}/api/v2/price/calc"

    payload = {
        "sender": {
            "country": "LT"    # your warehouse country
        },
        "receiver": {
            "country": country_code
        },
        "parcels": [{
            "count": 1,
            "weight": float(weight),
            "length": float(length),
            "width": float(width),
            "height": float(height),
        }]
    }

    headers = {
        "Content-Type": "application/json",
        "X-API-Key": SP_API_KEY
    }

    response = requests.post(url, headers=headers, data=json.dumps(payload))

    if response.status_code != 200:
        raise Exception(f"SP API error: {response.status_code} {response.text}")

    data = response.json()

    # SP returns carriers list → pick cheapest
    prices = [c["price"] for c in data.get("carriers", [])]
    if not prices:
        raise Exception("No carriers returned from SP")

    return min(prices)   # return cheapest shipping price
