from __future__ import annotations

import argparse
import html
import json
import os
import re
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta, timezone
from html.parser import HTMLParser
from pathlib import Path
from typing import Any, Iterable
from urllib.error import HTTPError, URLError
from urllib.parse import urljoin, urlparse, urlunparse
from urllib.request import Request, urlopen


ROOT = Path(__file__).resolve().parents[1]
CONFIG_PATH = ROOT / "crawler" / "places_config.json"
OUTPUT_PATH = ROOT / "docs" / "data" / "restaurants.json"
PLACES_URL = "https://places.googleapis.com/v1/places:searchNearby"
REQUEST_TIMEOUT = 15
DISCOVERY_VERSION = 2

SPECIAL_LINK = re.compile(
    r"\b(?:happy[\s_-]*hour|daily[\s_-]*specials?|weekday[\s_-]*specials?|"
    r"weekly[\s_-]*specials?|food[\s_-]*specials?|drink[\s_-]*specials?|"
    r"restaurant[\s_-]*specials?|promotions?|coupons?|deals?)\b",
    re.I,
)
WEAK_SPECIAL_LINK = re.compile(r"\bspecials?\b", re.I)
BLOCKED_HOSTS = {
    "facebook.com",
    "instagram.com",
    "linktr.ee",
    "opentable.com",
    "toasttab.com",
    "yelp.com",
}


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def iso(value: datetime) -> str:
    return value.astimezone(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def parse_iso(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def load_json(path: Path, fallback: Any) -> Any:
    try:
        return json.loads(path.read_text())
    except (FileNotFoundError, json.JSONDecodeError):
        return fallback


def should_refresh(refresh_days: int, force: bool) -> bool:
    if force:
        return True
    existing = load_json(OUTPUT_PATH, {})
    if existing.get("discovery_version") != DISCOVERY_VERSION:
        return True
    generated = parse_iso(existing.get("generated_at"))
    return not generated or utc_now() - generated >= timedelta(days=refresh_days)


def axis_values(start: float, end: float, step: float) -> Iterable[float]:
    current = start
    while current <= end + 0.000001:
        yield round(current, 6)
        current += step


def grid_points(config: dict[str, Any]) -> list[dict[str, Any]]:
    lat_step = config["grid"]["latitude_step"]
    lon_step = config["grid"]["longitude_step"]
    points: list[dict[str, Any]] = []
    for area in config["areas"]:
        bounds = area["bounds"]
        for latitude in axis_values(bounds["south"], bounds["north"], lat_step):
            for longitude in axis_values(bounds["west"], bounds["east"], lon_step):
                points.append({"city": area["city"], "latitude": latitude, "longitude": longitude})
    return points


def api_request(api_key: str, point: dict[str, Any], config: dict[str, Any]) -> list[dict[str, Any]]:
    body = json.dumps(
        {
            "includedPrimaryTypes": config["included_types"],
            "maxResultCount": 20,
            "rankPreference": "DISTANCE",
            "locationRestriction": {
                "circle": {
                    "center": {"latitude": point["latitude"], "longitude": point["longitude"]},
                    "radius": config["grid"]["radius_meters"],
                }
            },
        }
    ).encode("utf-8")
    field_mask = ",".join(
        [
            "places.id",
            "places.displayName",
            "places.formattedAddress",
            "places.location",
            "places.types",
            "places.primaryType",
            "places.businessStatus",
            "places.websiteUri",
            "places.googleMapsUri",
            "places.nationalPhoneNumber",
            "places.regularOpeningHours",
        ]
    )
    request = Request(
        PLACES_URL,
        data=body,
        headers={
            "Content-Type": "application/json",
            "X-Goog-Api-Key": api_key,
            "X-Goog-FieldMask": field_mask,
            "User-Agent": "deal-radar/2.0 (+https://github.com/nickgggg/food-deals)",
        },
        method="POST",
    )
    last_error: Exception | None = None
    for attempt in range(3):
        try:
            with urlopen(request, timeout=REQUEST_TIMEOUT) as response:
                return json.loads(response.read()).get("places", [])
        except HTTPError as exc:
            message = exc.read().decode("utf-8", errors="replace")[:500]
            last_error = RuntimeError(f"Places API HTTP {exc.code}: {message}")
            if exc.code not in {429, 500, 502, 503, 504}:
                break
        except (OSError, URLError, json.JSONDecodeError) as exc:
            last_error = exc
        time.sleep(2**attempt)
    raise RuntimeError(str(last_error or "Places API request failed"))


def city_from_address(address: str, fallback: str) -> str | None:
    for city in ("Huntington Beach", "Fountain Valley"):
        if re.search(rf"\b{re.escape(city)}\s*,\s*CA\b", address, re.I):
            return city
    return None if address else fallback


def normalize_hours(raw: dict[str, Any] | None) -> dict[str, list[dict[str, str]]]:
    if not raw:
        return {}
    days = ["sunday", "monday", "tuesday", "wednesday", "thursday", "friday", "saturday"]
    result: dict[str, list[dict[str, str]]] = {}
    for period in raw.get("periods", []):
        opened = period.get("open", {})
        closed = period.get("close", {})
        if "day" not in opened or "hour" not in opened or "hour" not in closed:
            continue
        day = days[int(opened["day"])]
        result.setdefault(day, []).append(
            {
                "open": f'{int(opened["hour"]):02d}:{int(opened.get("minute", 0)):02d}',
                "close": f'{int(closed["hour"]):02d}:{int(closed.get("minute", 0)):02d}',
            }
        )
    return result


def normalize_place(place: dict[str, Any], fallback_city: str) -> dict[str, Any] | None:
    address = place.get("formattedAddress", "")
    city = city_from_address(address, fallback_city)
    name = place.get("displayName", {}).get("text")
    location = place.get("location", {})
    if not city or not name or not place.get("id"):
        return None
    return {
        "place_id": place["id"],
        "name": name,
        "city": city,
        "address": address,
        "phone": place.get("nationalPhoneNumber", ""),
        "latitude": location.get("latitude"),
        "longitude": location.get("longitude"),
        "website_url": place.get("websiteUri", ""),
        "google_maps_url": place.get("googleMapsUri", ""),
        "business_status": place.get("businessStatus", "BUSINESS_STATUS_UNSPECIFIED"),
        "primary_type": place.get("primaryType", ""),
        "types": place.get("types", []),
        "hours": normalize_hours(place.get("regularOpeningHours")),
        "specials_pages": [],
    }


class LinkParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.links: list[tuple[str, str]] = []
        self.text: list[str] = []
        self._href: str | None = None
        self._anchor_parts: list[str] = []
        self._hidden = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in {"script", "style", "noscript", "svg"}:
            self._hidden += 1
        if tag == "a":
            self._href = dict(attrs).get("href")
            self._anchor_parts = []

    def handle_endtag(self, tag: str) -> None:
        if tag == "a" and self._href:
            self.links.append((self._href, " ".join(self._anchor_parts)))
            self._href = None
            self._anchor_parts = []
        if tag in {"script", "style", "noscript", "svg"} and self._hidden:
            self._hidden -= 1

    def handle_data(self, data: str) -> None:
        if self._hidden:
            return
        clean = re.sub(r"\s+", " ", html.unescape(data)).strip()
        if clean:
            self.text.append(clean)
            if self._href:
                self._anchor_parts.append(clean)


def host_key(url: str) -> str:
    return (urlparse(url).hostname or "").lower().removeprefix("www.")


def canonical_url(url: str) -> str:
    parsed = urlparse(url)
    return urlunparse((parsed.scheme or "https", parsed.netloc, parsed.path or "/", "", parsed.query, ""))


def blocked_website(url: str) -> bool:
    host = host_key(url)
    return any(host == blocked or host.endswith(f".{blocked}") for blocked in BLOCKED_HOSTS)


def fetch_homepage(url: str) -> str:
    request = Request(
        url,
        headers={
            "User-Agent": "deal-radar/2.0 (+https://github.com/nickgggg/food-deals)",
            "Accept": "text/html,application/xhtml+xml",
        },
    )
    with urlopen(request, timeout=REQUEST_TIMEOUT) as response:
        content_type = response.headers.get("Content-Type", "")
        if "html" not in content_type:
            return ""
        return response.read(2_000_000).decode(response.headers.get_content_charset() or "utf-8", errors="replace")


def discover_specials_pages(restaurant: dict[str, Any]) -> list[dict[str, Any]]:
    homepage = restaurant.get("website_url", "")
    if not homepage or blocked_website(homepage):
        return []
    try:
        page = fetch_homepage(homepage)
    except Exception:
        return []
    parser = LinkParser()
    parser.feed(page)
    home_host = host_key(homepage)
    candidates: dict[str, dict[str, Any]] = {}
    for href, label in parser.links:
        absolute = canonical_url(urljoin(homepage, href))
        if host_key(absolute) != home_host or urlparse(absolute).scheme not in {"http", "https"}:
            continue
        evidence = f"{label} {urlparse(absolute).path.replace('-', ' ').replace('_', ' ')}"
        if SPECIAL_LINK.search(evidence):
            candidates[absolute] = {"url": absolute, "label": label.strip() or "Specials", "confidence": "high"}
        elif WEAK_SPECIAL_LINK.search(evidence) and not re.search(r"menu|catering|gift", evidence, re.I):
            candidates[absolute] = {"url": absolute, "label": label.strip() or "Specials", "confidence": "medium"}
    visible_text = " ".join(parser.text)
    if SPECIAL_LINK.search(visible_text):
        absolute = canonical_url(homepage)
        candidates.setdefault(absolute, {"url": absolute, "label": "Website specials", "confidence": "medium"})
    return sorted(candidates.values(), key=lambda item: (item["confidence"] != "high", item["url"]))[:3]


def add_specials_pages(restaurants: list[dict[str, Any]]) -> None:
    operational = [item for item in restaurants if item["business_status"] == "OPERATIONAL" and item.get("website_url")]
    with ThreadPoolExecutor(max_workers=16) as executor:
        futures = {executor.submit(discover_specials_pages, item): item for item in operational}
        for future in as_completed(futures):
            futures[future]["specials_pages"] = future.result()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()
    config = load_json(CONFIG_PATH, {})
    if not config:
        raise RuntimeError(f"Missing discovery configuration: {CONFIG_PATH}")
    if not should_refresh(int(config.get("refresh_days", 7)), args.force):
        print("Restaurant inventory is fresh; skipping Places refresh")
        return 0

    api_key = os.environ.get("GOOGLE_PLACES_API_KEY", "").strip()
    if not api_key:
        raise RuntimeError("GOOGLE_PLACES_API_KEY is not available to this GitHub Actions workflow")

    points = grid_points(config)
    found: dict[str, dict[str, Any]] = {}
    failures: list[str] = []
    for index, point in enumerate(points, start=1):
        try:
            for raw in api_request(api_key, point, config):
                normalized = normalize_place(raw, point["city"])
                if normalized:
                    found[normalized["place_id"]] = normalized
        except Exception as exc:
            failures.append(f'{point["latitude"]},{point["longitude"]}: {exc}')
        if index % 25 == 0:
            print(f"Scanned {index}/{len(points)} map cells; found {len(found)} restaurants")

    success_count = len(points) - len(failures)
    if success_count < max(1, int(len(points) * 0.8)):
        sample = failures[0] if failures else "unknown error"
        raise RuntimeError(f"Places discovery failed for too many map cells ({success_count}/{len(points)} succeeded): {sample}")

    restaurants = sorted(found.values(), key=lambda item: (item["name"].casefold(), item["address"].casefold()))
    add_specials_pages(restaurants)
    now = utc_now()
    payload = {
        "discovery_version": DISCOVERY_VERSION,
        "generated_at": iso(now),
        "refresh_after": iso(now + timedelta(days=int(config.get("refresh_days", 7)))),
        "coverage": {
            "cities": [area["city"] for area in config["areas"]],
            "map_cells": len(points),
            "successful_map_cells": success_count,
            "failed_map_cells": len(failures),
            "restaurant_count": len(restaurants),
            "operational_count": sum(item["business_status"] == "OPERATIONAL" for item in restaurants),
            "closed_count": sum(item["business_status"] in {"CLOSED_TEMPORARILY", "CLOSED_PERMANENTLY"} for item in restaurants),
            "official_websites": sum(bool(item.get("website_url")) for item in restaurants),
            "specials_pages_found": sum(bool(item.get("specials_pages")) for item in restaurants),
        },
        "restaurants": restaurants,
    }
    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_PATH.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")
    print(f"Wrote {len(restaurants)} restaurants to {OUTPUT_PATH}")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as exc:
        print(f"Restaurant discovery failed: {exc}", file=sys.stderr)
        sys.exit(1)
