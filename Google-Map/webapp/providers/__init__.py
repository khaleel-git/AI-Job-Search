"""Listing providers. Each exposes ``search(query, ctx)`` yielding listing dicts:

{name, website, address, phone, rating, reviews, category, lat, lng, maps_url, sponsored, closed}
"""
from . import api_providers, selenium_maps

PROVIDERS = {
    "selenium_maps": selenium_maps.search,
    "places_api": api_providers.places_search,
    "serpapi": api_providers.serpapi_search,
    "outscraper": api_providers.outscraper_search,
}

CATALOG = [
    {"id": "selenium_maps", "name": "Selenium · Google Maps", "kind": "Discover", "secret": None,
     "about": "Drives Chrome, scrolls the results feed, opens each place. Free and slow; may break when Maps changes its UI."},
    {"id": "places_api", "name": "Google Places API (New)", "kind": "Discover", "secret": "GOOGLE_PLACES_KEY",
     "about": "Official Text Search with website, phone and rating in one call. Paid per request."},
    {"id": "serpapi", "name": "SerpAPI · Maps", "kind": "Discover", "secret": "SERPAPI_KEY",
     "about": "Google Maps results as JSON with pagination. No browser needed."},
    {"id": "outscraper", "name": "Outscraper", "kind": "Discover", "secret": "OUTSCRAPER_KEY",
     "about": "Bulk Maps results as JSON. Good for large sweeps."},
    {"id": "crawler", "name": "Built-in site crawler", "kind": "Enrich", "secret": None,
     "about": "Fetches homepage and ranked impressum / kontakt / karriere pages, extracts and de-obfuscates emails."},
    {"id": "hunter", "name": "Hunter.io", "kind": "Enrich + Verify", "secret": "HUNTER_KEY",
     "about": "Adds named contacts per domain and verifies addresses before outreach."},
    {"id": "nominatim", "name": "OpenStreetMap (Nominatim + Overpass)", "kind": "Geo", "secret": None,
     "about": "Suggests a city's districts and geocodes them. Replaces hand-built search URLs."},
]
