from __future__ import annotations

import hashlib
import html
import json
import re
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from html.parser import HTMLParser
from pathlib import Path
from typing import Iterable, TypedDict
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


ROOT = Path(__file__).resolve().parents[1]
SOURCES_PATH = ROOT / "crawler" / "sources.json"
OUTPUT_PATH = ROOT / "docs" / "data" / "deals.json"
STALE_AFTER_DAYS = 21
DROP_AFTER_DAYS = 90
REQUEST_TIMEOUT = 25
CRAWLER_VERSION = 3


DAYS = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]
DAY_LABELS = {
    "monday": "Mon",
    "tuesday": "Tue",
    "wednesday": "Wed",
    "thursday": "Thu",
    "friday": "Fri",
    "saturday": "Sat",
    "sunday": "Sun",
}


TAG_PATTERNS = {
    "percent_off": re.compile(r"\b(?:\d{1,3}\s*)?%\s*off\b|\b\d{1,3}\s*percent\s*off\b", re.I),
    "dollar_amount": re.compile(r"\$\s?\d+(?:\.\d{2})?(?:\s*(?:off|each|menu|special|taco|beer|wine|well|margarita|lunch|dinner|apps?|appetizers?|sliders?|drinks?))?", re.I),
    "bogo": re.compile(r"\b(?:bogo|buy\s+one(?:,?\s+get\s+one)?|two\s+for|2\s+for)\b", re.I),
    "happy_hour": re.compile(r"\bhappy\s+hour\b|\blate\s+night\b", re.I),
    "weekday_special": re.compile(r"\b(?:monday|tuesday|wednesday|thursday|friday|saturday|sunday|weekday|weekend|daily|all\s+day|taco\s+tuesday|wine\s+wednesday|brunch)\b", re.I),
    "free": re.compile(r"\bfree\b|\bcomplimentary\b", re.I),
    "deal_language": re.compile(r"\b(?:deal|special|discount|coupon|promo|promotion|offer|reward|rewards|limited\s+time|save|savings|half\s+off|1/2\s+off)\b", re.I),
}


NOISE_PATTERNS = [
    re.compile(r"^(skip to|copyright|privacy policy|terms|accessibility|do not sell)", re.I),
    re.compile(r"^(facebook|instagram|twitter|x|youtube|tiktok)$", re.I),
    re.compile(r"\b(?:cookie preferences|privacy policy|report abuse|powered by|yelp rating|read more|linktree|canva|analytics|sponsored links)\b", re.I),
    re.compile(r"\b(?:expired|click to use coupon|share|grubhub|doordash|uber eats|postmates)\b", re.I),
]


STRONG_TAGS = {"percent_off", "dollar_amount", "bogo", "happy_hour", "free"}
SPECIAL_CONTEXT = re.compile(
    r"\b(?:special|deal|discount|coupon|promo|promotion|offer|happy hour|taco tuesday|wine wednesday|brunch|lunch|dinner|menu)\b",
    re.I,
)

VALIDITY_CONTEXT = re.compile(
    r"\b(?:happy hour|daily|every day|all day|weekday|weekend|monday|tuesday|wednesday|thursday|friday|saturday|sunday|mon|tue|tues|wed|thu|thur|thurs|fri|sat|sun|am|pm|valid|dine in|carry out|coupon|limited time)\b",
    re.I,
)
STANDALONE_CONTEXT = re.compile(
    r"^(?:dine in only|not valid|valid with coupon only|available dine in|offer good only|prices and availability|regular price)",
    re.I,
)
TIME_RANGE = re.compile(
    r"\b(\d{1,2})(?::(\d{2}))?\s*(am|pm)?\s*(?:-|to|thru|through|until)\s*(\d{1,2})(?::(\d{2}))?\s*(am|pm)\b",
    re.I,
)
FOOD_TERMS = re.compile(
    r"\b(?:app|apps|appetizer|bite|brunch|breakfast|lunch|dinner|meal|menu|taco|pizza|wing|burger|sandwich|salad|pasta|chicken|steak|seafood|soup|dessert|fries|entree|platter|combo|soda)\b",
    re.I,
)
DRINK_TERMS = re.compile(
    r"\b(?:beer|beers|wine|wines|vino|cocktail|cocktails|margarita|margaritas|drink|drinks|bar|well|draft|pint|pints|mug|mugs|pitcher|pitchers|sangria|tequila|vodka|whiskey|bourbon|beverage)\b",
    re.I,
)


class Candidate(TypedDict):
    text: str
    summary: str
    details: list[str]


class VisibleTextParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._hidden_depth = 0
        self._parts: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in {"script", "style", "noscript", "svg", "iframe"}:
            self._hidden_depth += 1
        if tag in {"br", "p", "div", "li", "section", "article", "h1", "h2", "h3", "h4", "tr"}:
            self._parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag in {"script", "style", "noscript", "svg", "iframe"} and self._hidden_depth:
            self._hidden_depth -= 1
        if tag in {"p", "div", "li", "section", "article", "h1", "h2", "h3", "h4", "tr"}:
            self._parts.append("\n")

    def handle_data(self, data: str) -> None:
        if not self._hidden_depth:
            self._parts.append(data)

    def lines(self) -> list[str]:
        text = html.unescape(" ".join(self._parts))
        raw_lines = re.split(r"[\n\r]+", text)
        cleaned: list[str] = []
        for raw in raw_lines:
            line = re.sub(r"\s+", " ", raw).strip()
            if line:
                cleaned.append(line)
        return cleaned


@dataclass(frozen=True)
class Source:
    name: str
    city: str
    url: str
    notes: str = ""


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def parse_iso(value: str | None, fallback: datetime) -> datetime:
    if not value:
        return fallback
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return fallback


def load_sources() -> list[Source]:
    raw_sources = json.loads(SOURCES_PATH.read_text())
    return [Source(**raw) for raw in raw_sources]


def load_existing() -> dict[str, dict]:
    if not OUTPUT_PATH.exists():
        return {}
    try:
        raw = json.loads(OUTPUT_PATH.read_text())
    except json.JSONDecodeError:
        return {}
    if raw.get("crawler_version") != CRAWLER_VERSION:
        return {}
    return {deal["id"]: deal for deal in raw.get("deals", []) if "id" in deal}


def fetch_html(source: Source) -> str:
    headers = {
        "User-Agent": "food-deals-bot/1.0 (+https://github.com/nickgggg/food-deals)",
        "Accept": "text/html,application/xhtml+xml",
    }
    request = Request(source.url, headers=headers)
    try:
        with urlopen(request, timeout=REQUEST_TIMEOUT) as response:
            charset = response.headers.get_content_charset() or "utf-8"
            return response.read().decode(charset, errors="replace")
    except HTTPError as exc:
        raise RuntimeError(f"HTTP {exc.code}") from exc
    except URLError as exc:
        raise RuntimeError(str(exc.reason)) from exc


def clean_text(html: str) -> list[str]:
    parser = VisibleTextParser()
    parser.feed(html)
    lines: list[str] = []
    for line in parser.lines():
        if not line or len(line) < 3:
            continue
        if any(pattern.search(line) for pattern in NOISE_PATTERNS):
            continue
        lines.append(line)
    return lines


def normalize_line(line: str) -> str:
    return re.sub(r"\s+", " ", line).strip(" -|\u2022")


def line_tags(line: str) -> list[str]:
    return detect_tags(line)


def starts_new_deal(line: str) -> bool:
    if re.match(r"^\$ ?\d", line):
        return True
    if re.match(r"^(?:free|happy hour|taco tuesday|wine wednesday|kids eat free)\b", line, re.I):
        return True
    return bool(TAG_PATTERNS["percent_off"].search(line) or TAG_PATTERNS["bogo"].search(line))


def is_context_line(line: str) -> bool:
    return bool(VALIDITY_CONTEXT.search(line) or TIME_RANGE.search(line))


def context_prefix(lines: list[str], index: int) -> list[str]:
    prefix: list[str] = []
    for line in lines[max(0, index - 3) : index]:
        clean = normalize_line(line)
        if is_context_line(clean) or clean.lower() in {"happy hour", "specials", "daily specials"}:
            prefix.append(clean)
    return prefix[-3:]


def context_suffix(lines: list[str], index: int) -> list[str]:
    suffix: list[str] = []
    for line in lines[index + 1 : min(len(lines), index + 7)]:
        clean = normalize_line(line)
        if not clean or any(pattern.search(clean) for pattern in NOISE_PATTERNS):
            continue
        if starts_new_deal(clean):
            break
        if len(clean) > 180 and not is_context_line(clean):
            continue
        if detect_tags(clean) or is_context_line(clean) or len(clean.split()) <= 12:
            suffix.append(clean)
        if len(suffix) >= 5:
            break
    return suffix


def candidate_windows(lines: list[str]) -> Iterable[Candidate]:
    seen: set[str] = set()
    for index, line in enumerate(lines):
        chunks = [normalize_line(line)]
        chunks.extend(re.split(r"(?<=[.!?])\s+", line))
        for chunk in chunks:
            normalized = normalize_line(chunk)
            if 8 <= len(normalized) <= 500 and normalized.lower() not in seen:
                tags = line_tags(normalized)
                if not tags or not is_quality_candidate(normalized, tags):
                    continue
                details = context_prefix(lines, index) + context_suffix(lines, index)
                details = [item for item in details if item and item.lower() != normalized.lower()]
                text = " ".join([normalized, *details])
                seen.add(normalized.lower())
                yield {
                    "text": normalize_line(text),
                    "summary": normalized,
                    "details": dedupe(details),
                }


def detect_tags(text: str) -> list[str]:
    return [tag for tag, pattern in TAG_PATTERNS.items() if pattern.search(text)]


def dedupe(items: Iterable[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for item in items:
        key = item.lower()
        if key in seen:
            continue
        seen.add(key)
        result.append(item)
    return result


def is_quality_candidate(text: str, tags: list[str]) -> bool:
    if any(pattern.search(text) for pattern in NOISE_PATTERNS):
        return False
    if STANDALONE_CONTEXT.search(text):
        return False
    if len(text.split()) < 2:
        return False
    if text.startswith("&") and not STRONG_TAGS.intersection(tags):
        return False
    if STRONG_TAGS.intersection(tags):
        return True
    return bool(SPECIAL_CONTEXT.search(text))


def extract_days(text: str) -> list[str]:
    lower = text.lower()
    if re.search(r"\b(?:daily|every day|all day|everyday)\b", lower):
        return DAYS
    if re.search(r"\b(?:weekday|weekdays|monday\s*(?:-|to|thru|through)\s*friday|mon\s*(?:-|to|thru|through)\s*fri)\b", lower):
        return DAYS[:5]
    if re.search(r"\b(?:weekend|weekends)\b", lower):
        return DAYS[5:]

    found: list[str] = []
    aliases = {
        "mon": "monday",
        "monday": "monday",
        "tue": "tuesday",
        "tues": "tuesday",
        "tuesday": "tuesday",
        "wed": "wednesday",
        "wednesday": "wednesday",
        "thu": "thursday",
        "thur": "thursday",
        "thurs": "thursday",
        "thursday": "thursday",
        "fri": "friday",
        "friday": "friday",
        "sat": "saturday",
        "saturday": "saturday",
        "sun": "sunday",
        "sunday": "sunday",
    }
    for match in re.finditer(r"\b(mon(?:day)?|tues?|tuesday|wed(?:nesday)?|thu(?:r|rs|rsday)?|thursday|fri(?:day)?|sat(?:urday)?|sun(?:day)?)\b", lower):
        day = aliases.get(match.group(1))
        if day and day not in found:
            found.append(day)
    return found


def normalize_time(hour: str, minute: str | None, period: str | None) -> str:
    suffix = f" {period.upper()}" if period else ""
    return f"{int(hour)}:{minute}{suffix}" if minute else f"{int(hour)}{suffix}"


def extract_time_window(text: str) -> str | None:
    match = TIME_RANGE.search(text)
    if not match:
        return None
    start_period = match.group(3) or match.group(6)
    start = normalize_time(match.group(1), match.group(2), start_period)
    end = normalize_time(match.group(4), match.group(5), match.group(6))
    return f"{start} - {end}"


def day_label(days: list[str]) -> str | None:
    if not days:
        return None
    if days == DAYS:
        return "Every day"
    if days == DAYS[:5]:
        return "Mon-Fri"
    if days == DAYS[5:]:
        return "Weekend"
    return ", ".join(DAY_LABELS[day] for day in days)


def category_for(text: str) -> list[str]:
    categories: list[str] = []
    if FOOD_TERMS.search(text):
        categories.append("food")
    if DRINK_TERMS.search(text):
        categories.append("drink")
    return categories or ["general"]


def validity_for(text: str, days: list[str], time_window: str | None) -> str:
    parts = [part for part in [day_label(days), time_window] if part]
    if parts:
        return ", ".join(parts)
    return "Check source for current day/time"


def deal_id(source: Source, candidate_text: str) -> str:
    stable_text = re.sub(r"\s+", " ", candidate_text.lower()).strip()
    digest = hashlib.sha1(f"{source.url}|{stable_text}".encode("utf-8")).hexdigest()
    return digest[:16]


def crawl_source(source: Source, now: datetime, existing: dict[str, dict]) -> tuple[list[dict], dict]:
    html = fetch_html(source)
    lines = clean_text(html)
    deals: list[dict] = []

    for candidate in candidate_windows(lines):
        candidate_text = candidate["text"]
        tags = detect_tags(candidate_text)
        days = extract_days(candidate_text)
        time_window = extract_time_window(candidate_text)

        did = deal_id(source, candidate_text)
        previous = existing.get(did, {})
        first_seen = previous.get("first_seen") or iso(now)
        deals.append(
            {
                "id": did,
                "restaurant": source.name,
                "city": source.city,
                "source_url": source.url,
                "source_notes": source.notes,
                "candidate_text": candidate_text,
                "summary": candidate["summary"],
                "details": candidate["details"],
                "tags": tags,
                "categories": category_for(candidate_text),
                "applies_days": days,
                "time_window": time_window,
                "validity": validity_for(candidate_text, days, time_window),
                "first_seen": first_seen,
                "last_seen": iso(now),
                "status": "active",
                "is_stale": False,
                "days_since_seen": 0,
            }
        )

    status = {
        "name": source.name,
        "city": source.city,
        "url": source.url,
        "ok": True,
        "candidate_count": len(deals),
        "checked_at": iso(now),
    }
    return deals, status


def carry_forward_stale(existing: dict[str, dict], seen_ids: set[str], now: datetime) -> list[dict]:
    stale_deals: list[dict] = []
    for did, deal in existing.items():
        if did in seen_ids:
            continue
        last_seen_dt = parse_iso(deal.get("last_seen"), now)
        days_since_seen = max(0, (now - last_seen_dt).days)
        if days_since_seen > DROP_AFTER_DAYS:
            continue
        tags = deal.get("tags", [])
        if not is_quality_candidate(deal.get("candidate_text", ""), tags):
            continue

        carried = dict(deal)
        carried["status"] = "stale"
        carried["is_stale"] = True
        carried["days_since_seen"] = days_since_seen
        carried["stale_after_days"] = STALE_AFTER_DAYS
        carried.setdefault("summary", carried.get("candidate_text", ""))
        carried.setdefault("details", [])
        carried.setdefault("categories", category_for(carried.get("candidate_text", "")))
        carried.setdefault("applies_days", extract_days(carried.get("candidate_text", "")))
        carried.setdefault("time_window", extract_time_window(carried.get("candidate_text", "")))
        carried.setdefault(
            "validity",
            validity_for(
                carried.get("candidate_text", ""),
                carried["applies_days"],
                carried["time_window"],
            ),
        )
        stale_deals.append(carried)
    return stale_deals


def sort_deals(deals: list[dict]) -> list[dict]:
    return sorted(
        deals,
        key=lambda deal: (
            deal.get("status") != "active",
            deal.get("city", ""),
            deal.get("restaurant", ""),
            deal.get("candidate_text", ""),
        ),
    )


def main() -> int:
    now = utc_now()
    sources = load_sources()
    existing = load_existing()
    all_deals: list[dict] = []
    source_status: list[dict] = []

    for source in sources:
        try:
            deals, status = crawl_source(source, now, existing)
        except Exception as exc:
            status = {
                "name": source.name,
                "city": source.city,
                "url": source.url,
                "ok": False,
                "error": f"{type(exc).__name__}: {exc}",
                "checked_at": iso(now),
            }
            deals = []
        all_deals.extend(deals)
        source_status.append(status)

    seen_ids = {deal["id"] for deal in all_deals}
    all_deals.extend(carry_forward_stale(existing, seen_ids, now))
    active_count = sum(1 for deal in all_deals if deal.get("status") == "active")
    stale_count = sum(1 for deal in all_deals if deal.get("status") == "stale")

    payload = {
        "crawler_version": CRAWLER_VERSION,
        "generated_at": iso(now),
        "scope": {
            "cities": sorted({source.city for source in sources}),
            "source_count": len(sources),
            "stale_after_days": STALE_AFTER_DAYS,
            "drop_after_days": DROP_AFTER_DAYS,
        },
        "summary": {
            "active_deals": active_count,
            "stale_deals": stale_count,
            "total_deals": len(all_deals),
            "healthy_sources": sum(1 for item in source_status if item["ok"]),
            "failed_sources": sum(1 for item in source_status if not item["ok"]),
        },
        "sources": source_status,
        "deals": sort_deals(all_deals),
    }

    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_PATH.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")
    print(f"Wrote {len(all_deals)} deals to {OUTPUT_PATH}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
