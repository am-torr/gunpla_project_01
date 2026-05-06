# app/scrapers/_selectors.py
"""
PROPRIETARY: HLJ-specific selectors and extraction patterns
This module contains competitive IP refined through testing and iteration.
"""

class HLJSelectors:
    """CSS selectors for Hobby Link Japan scraping"""

    # Product listing page selectors
    PRODUCT_CARD = ".search-widget-block"
    PRODUCT_NAME = ".product-item-name a"
    PRODUCT_PRICE = '[id$="_price"]'
    PRODUCT_IMAGE = "img"
    STOCK_STATUS = '[id$="_stockStatusDetail"]'
    ON_SALE_FLAG = '[id$="_is_on_sale"]'

    # Waiting selectors
    PRICE_LOADED = '[id$="_price"]:not(:empty)'


class HLJPatterns:
    """Regex patterns for detail page extraction"""

    # Product codes and identifiers
    CODE_TEXT = r'Code:\s*(\w+)'
    CODE_URL = r'([a-z]{3,4}\d+(?:-up)?)'
    JAN_CODE = r'JAN Code:\s*(\d+)'

    # Dates
    RELEASE_DATE = r'Release Date:\s*(.+?)(?:\s|$)'
    CANCELLATION_DEADLINE = r'Cancellation Deadline:\s*(\d{4}-\d{2}-\d{2})'

    # Dimensions and weight
    DIMENSIONS = r'([\d.]+\s*x\s*[\d.]+\s*x\s*[\d.]+\s*cm)'
    WEIGHT = r'(\d+g)'

    # Text matching patterns
    CATEGORY_LABEL = r'Category:'
    SERIES_LABEL = r'Series:'
    DESCRIPTION_LABEL = r'Description'
    INCLUDES_LABEL = r'\[Includes\]'
    COUNTRY_LABEL = r'Country of Origin:'
    MANUFACTURER_LABEL = r'Manufacturer:'
    ITEM_TYPE_LABEL = r'Item Type:'
    ITEM_SIZE_LABEL = r'Item Size/Weight:'


