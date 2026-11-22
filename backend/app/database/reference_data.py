"""Fictional reference (dimension) data. No real customer, cardholder or bank data is used."""

MERCHANT_CATEGORIES = {
    # category: (median ticket in INR, lognormal sigma)
    "E-commerce": (1200, 0.75),
    "Food Delivery": (450, 0.55),
    "Travel": (6500, 0.80),
    "Electronics": (9000, 0.85),
    "Grocery": (800, 0.60),
    "Utilities": (1500, 0.50),
    "Education": (12000, 0.70),
    "Healthcare": (2000, 0.70),
}

# merchant_id, name, category, region, risk_tier, status, settlement bank, volume weight, success adj
MERCHANTS = [
    ("M001", "ShopSphere Online", "E-commerce", "North", "LOW", "ACTIVE", "B01", 9.0, 0.000),
    ("M002", "CartNest Retail", "E-commerce", "West", "LOW", "ACTIVE", "B02", 7.0, 0.005),
    ("M003", "QuickBite Foods", "Food Delivery", "South", "LOW", "ACTIVE", "B03", 8.0, 0.005),
    ("M004", "TiffinTrail", "Food Delivery", "West", "MEDIUM", "ACTIVE", "B04", 5.0, 0.000),
    ("M005", "SkyRoute Travels", "Travel", "North", "MEDIUM", "ACTIVE", "B01", 4.0, -0.010),
    ("M006", "RailYatra Booking", "Travel", "East", "LOW", "ACTIVE", "B06", 3.5, 0.000),
    ("M007", "VoltMart Electronics", "Electronics", "South", "MEDIUM", "ACTIVE", "B02", 3.0, -0.005),
    ("M008", "GadgetGalaxy", "Electronics", "West", "HIGH", "ACTIVE", "B05", 2.5, -0.015),
    ("M009", "FreshBasket Grocers", "Grocery", "South", "LOW", "ACTIVE", "B03", 6.5, 0.005),
    ("M010", "DailyNeeds Mart", "Grocery", "East", "LOW", "ACTIVE", "B07", 5.0, 0.000),
    ("M011", "PowerGrid Utilities", "Utilities", "North", "LOW", "ACTIVE", "B08", 4.5, 0.010),
    ("M012", "AquaFlow Water Board", "Utilities", "East", "LOW", "ACTIVE", "B06", 2.5, 0.010),
    ("M013", "BrightPath Academy", "Education", "South", "LOW", "ACTIVE", "B04", 2.0, 0.000),
    ("M014", "SkillForge Learning", "Education", "North", "MEDIUM", "ACTIVE", "B08", 2.0, -0.005),
    ("M015", "CarePlus Pharmacy", "Healthcare", "West", "LOW", "ACTIVE", "B02", 3.5, 0.005),
    ("M016", "MediQuick Labs", "Healthcare", "East", "MEDIUM", "ACTIVE", "B07", 2.0, 0.000),
    # Seeded statistical outlier: high-risk merchant with elevated risk declines.
    ("M017", "LuxeDeals Flash Sales", "E-commerce", "North", "HIGH", "ACTIVE", "B05", 3.0, -0.110),
    ("M018", "UrbanKart", "E-commerce", "South", "MEDIUM", "ACTIVE", "B03", 4.0, 0.000),
    ("M019", "MetroEats", "Food Delivery", "North", "LOW", "ACTIVE", "B01", 4.5, 0.000),
    ("M020", "HolidayNest Stays", "Travel", "West", "MEDIUM", "ACTIVE", "B06", 2.0, -0.005),
    ("M021", "HomeHub Appliances", "Electronics", "East", "LOW", "ACTIVE", "B08", 2.0, 0.000),
    ("M022", "GreenLeaf Organics", "Grocery", "West", "LOW", "INACTIVE", "B04", 1.0, 0.000),
    ("M023", "CityGas Connect", "Utilities", "South", "LOW", "ACTIVE", "B03", 2.0, 0.010),
    ("M024", "WellnessFirst Clinics", "Healthcare", "North", "LOW", "ACTIVE", "B01", 1.5, 0.000),
]

# bank_id, name, type, region, status, volume weight, success adj
BANKS = [
    ("B01", "Aurora National Bank", "PUBLIC", "North", "ACTIVE", 16.0, 0.010),
    ("B02", "Bharat Union Bank", "PUBLIC", "West", "ACTIVE", 14.0, 0.005),
    ("B03", "Deccan Commercial Bank", "PRIVATE", "South", "ACTIVE", 18.0, 0.000),
    ("B04", "Eastern Coastal Bank", "PRIVATE", "East", "ACTIVE", 10.0, -0.010),
    ("B05", "Frontier Co-operative Bank", "COOPERATIVE", "West", "ACTIVE", 6.0, -0.025),
    ("B06", "Ganga Valley Bank", "PUBLIC", "East", "ACTIVE", 12.0, 0.005),
    ("B07", "Horizon Payments Bank", "PAYMENTS_BANK", "South", "ACTIVE", 9.0, -0.005),
    ("B08", "Indus Private Bank", "PRIVATE", "North", "ACTIVE", 15.0, 0.010),
]

# payment_method_id, name, category, instrument, base share, base success probability
PAYMENT_METHODS = [
    ("PM01", "UPI", "UPI", "VPA", 0.55, 0.945),
    ("PM02", "Debit Card", "CARD", "DEBIT_CARD", 0.17, 0.905),
    ("PM03", "Credit Card", "CARD", "CREDIT_CARD", 0.16, 0.925),
    ("PM04", "Net Banking", "NETBANKING", "BANK_ACCOUNT", 0.12, 0.800),
]

FAILURE_CODES = [
    "INSUFFICIENT_FUNDS",
    "INCORRECT_PIN_OTP",
    "BANK_TIMEOUT",
    "ISSUER_DECLINED",
    "RISK_DECLINED",
    "NETWORK_ERROR",
    "LIMIT_EXCEEDED",
]

# Failure-code mix per payment method (same order as FAILURE_CODES).
FAILURE_CODE_WEIGHTS = {
    "PM01": [0.28, 0.22, 0.18, 0.08, 0.04, 0.12, 0.08],
    "PM02": [0.30, 0.20, 0.12, 0.18, 0.06, 0.06, 0.08],
    "PM03": [0.10, 0.18, 0.10, 0.30, 0.14, 0.06, 0.12],
    "PM04": [0.15, 0.25, 0.30, 0.10, 0.03, 0.12, 0.05],
}

VALID_STATUSES = ("SUCCESS", "FAILED", "PENDING")

# Hour-of-day traffic profile (IST), index = hour.
HOURLY_WEIGHTS = [
    0.6, 0.4, 0.3, 0.2, 0.2, 0.3, 0.6, 1.2, 2.0, 2.8, 3.4, 3.8,
    4.4, 4.6, 4.0, 3.6, 3.5, 3.8, 4.4, 5.2, 5.6, 5.0, 3.6, 1.8,
]

# Scenario-specific seeded effects --------------------------------------------
DECLINE_BANK_ID = "B03"          # Scenario B: Deccan Commercial Bank
DECLINE_SUCCESS_DROP = 0.22      # absolute drop in success probability
DECLINE_DAYS = 7                 # last N days of the window
DISCREPANCY_BANK_ID = "B06"      # Scenario G: Ganga Valley Bank
MISSING_REPORT_BANK_ID = "B02"   # Scenario G: one missing daily report
MIX_SHIFT_SHARES = {"PM01": 0.28, "PM02": 0.17, "PM03": 0.16, "PM04": 0.39}  # Scenario D, last 7 days
