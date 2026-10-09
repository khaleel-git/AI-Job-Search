"""HTTP providers: Google Places API (New), SerpAPI, Outscraper, Hunter.io, OSM geo."""
import requests

from .. import secrets_store

TIMEOUT = 30


class ProviderError(RuntimeError):
    pass


def _key(name):
    key = secrets_store.get(name)
    if not key:
        raise ProviderError(f"{name} is not set. Add it under Data Sources.")
    return key


def _check(resp, label):
    if resp.status_code >= 400:
        raise ProviderError(f"{label} returned HTTP {resp.status_code}: {resp.text[:200]}")
    return resp.json()


PLACES_FIELDS = ",".join([
    "places.displayName", "places.websiteUri", "places.formattedAddress", "places.nationalPhoneNumber",
    "places.rating", "places.userRatingCount", "places.primaryTypeDisplayName", "places.location",
    "places.googleMapsUri", "places.businessStatus", "nextPageToken",
])


def places_search(query, ctx):
    key = _key("GOOGLE_PLACES_KEY")
    body = {"textQuery": query, "pageSize": 20, "languageCode": ctx.search.get("language", "de")}
    seen = 0
    while seen < ctx.max_results:
        data = _check(requests.post(
            "https://places.googleapis.com/v1/places:searchText", json=body, timeout=TIMEOUT,
            headers={"X-Goog-Api-Key": key, "X-Goog-FieldMask": PLACES_FIELDS}), "Places API")
        for p in data.get("places", []):
            seen += 1
            loc = p.get("location") or {}
            yield {
                "name": (p.get("displayName") or {}).get("text"),
                "website": p.get("websiteUri"),
                "address": p.get("formattedAddress"),
                "phone": p.get("nationalPhoneNumber"),
                "rating": p.get("rating"),
                "reviews": p.get("userRatingCount"),
                "category": (p.get("primaryTypeDisplayName") or {}).get("text"),
                "lat": loc.get("latitude"), "lng": loc.get("longitude"),
                "maps_url": p.get("googleMapsUri"),
                "sponsored": False,
                "closed": p.get("businessStatus") not in (None, "OPERATIONAL"),
            }
        token = data.get("nextPageToken")
        if not token or ctx.should_stop():
            return
        body["pageToken"] = token


def serpapi_search(query, ctx):
    key = _key("SERPAPI_KEY")
    start = 0
    while start < ctx.max_results:
        data = _check(requests.get("https://serpapi.com/search.json", timeout=TIMEOUT, params={
            "engine": "google_maps", "type": "search", "q": query, "hl": ctx.search.get("language", "de"),
            "start": start, "api_key": key}), "SerpAPI")
        results = data.get("local_results") or []
        for p in results:
            gps = p.get("gps_coordinates") or {}
            yield {
                "name": p.get("title"), "website": p.get("website"), "address": p.get("address"),
                "phone": p.get("phone"), "rating": p.get("rating"), "reviews": p.get("reviews"),
                "category": p.get("type"), "lat": gps.get("latitude"), "lng": gps.get("longitude"),
                "maps_url": p.get("place_id_search"), "sponsored": False,
                "closed": "permanently closed" in str(p.get("open_state", "")).lower(),
            }
        if len(results) < 20 or ctx.should_stop():
            return
        start += 20


def outscraper_search(query, ctx):
    key = _key("OUTSCRAPER_KEY")
    data = _check(requests.get("https://api.app.outscraper.com/maps/search-v3", timeout=180,
                               headers={"X-API-KEY": key},
                               params={"query": query, "limit": ctx.max_results, "async": "false",
                                       "language": ctx.search.get("language", "de")}), "Outscraper")
    batches = data.get("data") or []
    for batch in batches:
        for p in batch or []:
            yield {
                "name": p.get("name"), "website": p.get("site"), "address": p.get("full_address"),
                "phone": p.get("phone"), "rating": p.get("rating"), "reviews": p.get("reviews"),
                "category": p.get("type"), "lat": p.get("latitude"), "lng": p.get("longitude"),
                "maps_url": p.get("location_link"), "sponsored": False,
                "closed": p.get("business_status") not in (None, "OPERATIONAL"),
            }


def hunter_domain_emails(domain):
    key = _key("HUNTER_KEY")
    data = _check(requests.get("https://api.hunter.io/v2/domain-search", timeout=TIMEOUT,
                               params={"domain": domain, "api_key": key, "limit": 10}), "Hunter")
    return [e["value"] for e in (data.get("data") or {}).get("emails", []) if e.get("value")]


def hunter_verify(email):
    key = _key("HUNTER_KEY")
    data = _check(requests.get("https://api.hunter.io/v2/email-verifier", timeout=TIMEOUT,
                               params={"email": email, "api_key": key}), "Hunter")
    return (data.get("data") or {}).get("status", "unknown")


OSM_HEADERS = {"User-Agent": "MapLeads/1.0 (local job-search tool)"}
OVERPASS_SERVERS = ["https://overpass-api.de/api/interpreter", "https://overpass.kumi.systems/api/interpreter",
                    "https://maps.mail.ru/osm/tools/overpass/api/interpreter"]


def suggest_districts(city):
    """District names inside a city via Overpass (admin_level 9/10, falling back to suburbs)."""
    q = f"""[out:json][timeout:25];
area["name"="{city.replace('"', '')}"]["boundary"="administrative"]->.a;
(rel(area.a)["boundary"="administrative"]["admin_level"~"^(9|10)$"];);
out tags;"""
    data, last_error = None, None
    # The public Overpass servers are often overloaded; try a mirror before giving up.
    for server in OVERPASS_SERVERS:
        try:
            resp = requests.post(server, data={"data": q}, headers=OSM_HEADERS, timeout=60)
            if resp.status_code == 200:
                data = resp.json()
                break
            last_error = f"HTTP {resp.status_code}"
        except requests.RequestException as e:
            last_error = type(e).__name__
    if data is None:
        raise ProviderError(f"OpenStreetMap district lookup is busy ({last_error}). Try again in a minute.")
    names = {e["tags"]["name"] for e in data.get("elements", []) if e.get("tags", {}).get("name")}
    names.discard(city)
    return sorted(names)


def geocode(place):
    resp = requests.get("https://nominatim.openstreetmap.org/search", headers=OSM_HEADERS, timeout=TIMEOUT,
                        params={"q": place, "format": "json", "limit": 1})
    data = _check(resp, "Nominatim")
    if not data:
        return None
    return {"lat": float(data[0]["lat"]), "lng": float(data[0]["lon"]), "name": data[0].get("display_name")}


def test_key(provider):
    """Cheapest call that proves a key works."""
    if provider == "places_api":
        list(_take(places_search("Brandenburger Tor", _TestCtx()), 1))
    elif provider == "serpapi":
        _check(requests.get("https://serpapi.com/account.json", params={"api_key": _key("SERPAPI_KEY")},
                            timeout=TIMEOUT), "SerpAPI")
    elif provider == "outscraper":
        _check(requests.get("https://api.app.outscraper.com/profile/balance",
                            headers={"X-API-KEY": _key("OUTSCRAPER_KEY")}, timeout=TIMEOUT), "Outscraper")
    elif provider == "hunter":
        _check(requests.get("https://api.hunter.io/v2/account", params={"api_key": _key("HUNTER_KEY")},
                            timeout=TIMEOUT), "Hunter")
    else:
        raise ProviderError(f"{provider} has no key to test")
    return True


class _TestCtx:
    search = {"language": "de"}
    max_results = 1

    @staticmethod
    def should_stop():
        return True


def _take(it, n):
    for i, x in enumerate(it):
        if i >= n:
            return
        yield x
