import requests

def get_conversion_rate(to_currency: str) -> float:
    """Returns conversion rate from EUR to target currency."""
    if to_currency.upper() == "EUR":
        return 1.0

    try:
        response = requests.get(f"https://api.frankfurter.app/latest?from=EUR&to={to_currency}")
        response.raise_for_status()
        data = response.json()
        return data["rates"][to_currency.upper()]
    except Exception as e:
        # fallback to 1
        print("Error fetching conversion rate:", e)
        return 1.0