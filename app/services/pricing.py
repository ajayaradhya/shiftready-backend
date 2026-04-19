# app/services/pricing.py

class PricingEngine:
    # Sydney Resale Market Multipliers
    DEPRECIATION_RATES = {
        "electronics": 0.35, # Drops fast (JB Hi-Fi cycles)
        "furniture": 0.20,    # Holds value better (Koala/IKEA)
        "appliances": 0.15,   # High demand in rentals
        "default": 0.25
    }

    CONDITION_MULT = {
        "Like-New": 0.90,
        "Good": 0.70,
        "Visible Wear": 0.40
    }

    @classmethod
    def calculate_listing_price(cls, orig_price: float, category: str, condition: str, age_years: float = 1.0) -> float:
        rate = cls.DEPRECIATION_RATES.get(category.lower(), cls.DEPRECIATION_RATES["default"])
        multiplier = cls.CONDITION_MULT.get(condition, 0.50)
        
        # Compound Depreciation Formula: P = P_orig * (1 - rate)^t * multiplier
        suggested_price = orig_price * ((1 - rate) ** age_years) * multiplier
        
        return round(suggested_price / 5) * 5 