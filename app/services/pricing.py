class PricingEngine:
    # Depreciation rates (delta)
    DEPRECIATION_MAP = {
        "electronics": 0.25, # High turnover in Sydney
        "furniture": 0.15,
        "appliances": 0.10,
        "default": 0.20
    }

    # Condition multipliers (C_mult)
    CONDITION_MAP = {
        "Like-New": 0.95,
        "Good": 0.75,
        "Visible Wear": 0.50
    }

    @classmethod
    def calculate_listing_price(cls, orig_price: float, category: str, condition: str, years: float = 1.0) -> float:
        delta = cls.DEPRECIATION_MAP.get(category.lower(), cls.DEPRECIATION_MAP["default"])
        c_mult = cls.CONDITION_MAP.get(condition, 0.60)
        
        # P_list = P_orig * (1 - delta)^t * C_mult
        p_list = orig_price * ((1 - delta) ** years) * c_mult
        
        return round(p_list, 2)