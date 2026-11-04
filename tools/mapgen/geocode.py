"""Worldwide place lookup: address, place name or postcode -> (label, lon, lat).

* UK postcodes go to postcodes.io first (exact ONS centroids).
* Everything else (and the UK fallback) goes to Nominatim, the OpenStreetMap
  geocoder, which understands addresses, places and postcodes in most countries.
  Usage policy: max 1 request/second and an identifying User-Agent; results are
  cached so repeated runs don't hit the service.
"""

import hashlib
import json
import os
import re
import urllib.parse

UK_POSTCODE = re.compile(r"^[A-Z]{1,2}\d[A-Z\d]?\s*\d[A-Z]{2}$", re.IGNORECASE)
POSTCODES_IO = "https://api.postcodes.io/postcodes/{}"
NOMINATIM = "https://nominatim.openstreetmap.org/search?{}"


def geocode(query, http_get, cache_dir):
    """Return {"label", "lon", "lat", "source"} or None if nothing matched."""
    q = query.strip()
    if UK_POSTCODE.match(q):
        data = http_get(POSTCODES_IO.format(urllib.parse.quote(q.replace(" ", "").upper())))
        if data:
            r = json.loads(data)["result"]
            return {"label": r["postcode"], "lon": r["longitude"], "lat": r["latitude"],
                    "source": "postcodes.io"}

    key = hashlib.sha1(q.lower().encode()).hexdigest()[:16]
    url = NOMINATIM.format(urllib.parse.urlencode({"q": q, "format": "jsonv2", "limit": 1}))
    data = http_get(url, os.path.join(cache_dir, "geocode", f"{key}.json"))
    results = json.loads(data) if data else []
    if not results:
        return None
    r = results[0]
    return {"label": r.get("display_name", q), "lon": float(r["lon"]), "lat": float(r["lat"]),
            "source": "nominatim"}
