from __future__ import annotations

import hashlib
import html
import json
import re
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from html.parser import HTMLParser
from pathlib import Path
from typing import Any, Iterable, TypedDict
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


ROOT = Path(__file__).resolve().parents[1]
SOURCES_PATH = ROOT / "crawler" / "sources.json"
OUTPUT_PATH = ROOT / "docs" / "data" / "deals.json"
STALE_AFTER_DAYS = 21
DROP_AFTER_DAYS = 90
REQUEST_TIMEOUT = 25
CRAWLER_VERSION = 6


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
    "percent_off": re.compile(r"\b(?:\d{1,3}\s*)?%\s*off\b|\b\d{1,3}\s*percent\s*off\b|\bhalf\s+price\b|\b1/2\s*off\b", re.I),
    "dollar_amount": re.compile(r"\$\s?\d+(?:\.\d{2})?|\b\d+(?:\.\d{2})?\s*dollars?\b", re.I),
    "bogo": re.compile(r"\b(?:bogo|buy\s+one(?:,?\s+get\s+one)?|two\s+for|2\s+for|2-4-1)\b", re.I),
    "happy_hour": re.compile(r"\bhappy\s+hour\b|\blate\s+night\b", re.I),
    "weekday_special": re.compile(r"\b(?:monday|tuesday|wednesday|thursday|friday|saturday|sunday|weekday|weekend|daily|all\s+day|taco\s+tuesday|wine\s+wednesday|brunch)\b", re.I),
    "free": re.compile(r"\bfree\b|\bcomplimentary\b", re.I),
    "deal_language": re.compile(r"\b(?:deal|deals|special|specials|discount|coupon|promo|promotion|offer|reward|rewards|limited\s+time|save|savings|starting\s+at)\b", re.I),
}


NOISE_PATTERNS = [
    re.compile(r"^(skip to|copyright|privacy policy|terms|accessibility|do not sell)", re.I),
    re.compile(r"^(facebook|instagram|twitter|x|youtube|tiktok)$", re.I),
    re.compile(r"^(?:home|menu|menus|order|order online|reserve a table|book a table|contact us|careers|gallery|quick links|directions|vip club|content)$", re.I),
    re.compile(r"\border(?: online)?\b.*\babout\b.*\bgallery\b", re.I),
    re.compile(r"\bcontent\b.*\bmenus\b.*\breserve a table\b", re.I),
    re.compile(r"\b(?:cookie preferences|privacy policy|report abuse|powered by|yelp rating|read more|linktree|canva|analytics|sponsored links)\b", re.I),
    re.compile(r"\b(?:expired|click to use coupon|share|grubhub|doordash|uber eats|postmates|nutritional information|party trays|at your grocer)\b", re.I),
    re.compile(r"^[A-Z][a-z]+\s+[A-Z]\.$"),
]


LOW_VALUE_SUMMARY = re.compile(
    r"^(?:fountain valley coupon!?|happy hour specials|lunch specials|dinner specialties|all dinners include|our entire menu is available|corkage fee|add chicken|add salad|add soup or salad)",
    re.I,
)
MENU_PRICE_CONTEXT = re.compile(
    r"\b(?:order personal meals|personal meals|serves \d|kids meals|sides|desserts|crowd pleasers|wood fired grill|soups, salads|burgers, sandwiches|dinner specialties)\b",
    re.I,
)
PROMO_CONTEXT = re.compile(
    r"\b(?:off|free|bogo|2-4-1|buy one|half price|happy hour|special|specials|deal|deals|coupon|limited time|starting at|all day|weekday|weekend|taco tuesday|wine wednesday|kids eat free|with purchase|not valid|valid with coupon|available carry out|dine in only|each)\b",
    re.I,
)
VALIDITY_CONTEXT = re.compile(
    r"\b(?:happy hour|daily|every day|all day|weekday|weekend|monday|tuesday|wednesday|thursday|friday|saturday|sunday|mon|tue|tues|wed|thu|thur|thurs|fri|sat|sun|am|pm|valid|dine in|carry out|coupon|limited time|after|before|holidays)\b",
    re.I,
)
TIME_RANGE = re.compile(
    r"\b(\d{1,2})(?::(\d{2}))?\s*(am|pm)?\s*(?:-|to|thru|through|until|\u2013|\u2014)\s*(\d{1,2})(?::(\d{2}))?\s*(am|pm|close)\b",
    re.I,
)
FOOD_TERMS = re.compile(
    r"\b(?:app|apps|appetizer|bite|brunch|breakfast|lunch|dinner|meal|menu|taco|tacos|pizza|wing|wings|burger|sandwich|salad|pasta|chicken|steak|fish|seafood|soup|dessert|fries|entree|platter|combo|soda|meatloaf|spaghetti|prime rib|nachos|calamari|sliders)\b",
    re.I,
)
DRINK_TERMS = re.compile(
    r"\b(?:beer|beers|wine|wines|vino|cocktail|cocktails|margarita|margaritas|martini|martinis|drink|drinks|bar|well|draft|pint|pints|mug|mugs|pitcher|pitchers|sangria|tequila|vodka|whiskey|bourbon|beverage)\b",
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
        text = html.unescape("\n".join(self._parts))
        raw_lines = re.split(r"[\n\r]+", text)
        cleaned: list[str] = []
        for raw in raw_lines:
            line = normalize_line(raw)
            if line:
                cleaned.append(line)
        return cleaned


@dataclass(frozen=True)
class Source:
    name: str
    city: str
    url: str
    notes: str = ""
    location: dict[str, Any] = field(default_factory=dict)
    options: dict[str, Any] = field(default_factory=dict)


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


def normalize_line(line: str) -> str:
    return re.sub(r"\s+", " ", html.unescape(line)).strip(" -|\u2022\t")


def load_sources() -> list[Source]:
    raw_sources = json.loads(SOURCES_PATH.read_text())
    return [Source(**raw) for raw in raw_sources if not raw.get("retired")]


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
    last_error: Exception | None = None
    for attempt in range(3):
        try:
            with urlopen(request, timeout=REQUEST_TIMEOUT) as response:
                charset = response.headers.get_content_charset() or "utf-8"
                return response.read().decode(charset, errors="replace")
        except HTTPError as exc:
            if exc.code == 403:
                raise RuntimeError(f"HTTP {exc.code}") from exc
            last_error = exc
        except (OSError, URLError) as exc:
            last_error = exc
        if attempt < 2:
            time.sleep(2**attempt)
    raise RuntimeError(str(getattr(last_error, "reason", last_error)))


def clean_text(page_html: str) -> list[str]:
    parser = VisibleTextParser()
    parser.feed(page_html)
    lines: list[str] = []
    for line in parser.lines():
        if not line or len(line) < 3:
            continue
        if any(pattern.search(line) for pattern in NOISE_PATTERNS):
            continue
        lines.append(line)
    return lines


def detect_tags(text: str) -> list[str]:
    return [tag for tag, pattern in TAG_PATTERNS.items() if pattern.search(text)]


def dedupe(items: Iterable[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for item in items:
        clean = normalize_line(str(item))
        key = re.sub(r"\W+", " ", clean.lower()).strip()
        if not clean or key in seen:
            continue
        seen.add(key)
        result.append(clean)
    return result


def starts_new_deal(line: str) -> bool:
    if re.match(r"^\$ ?\d", line):
        return True
    if re.match(r"^(?:free|happy hour|taco tuesday|wine wednesday|kids eat free|meal deals|lunch specials|daily specials)\b", line, re.I):
        return True
    if re.search(r"\b(?:MONDAY|TUESDAY|WEDNESDAY|THURSDAY|FRIDAY|SATURDAY|SUNDAY)\b", line) and len(line.split()) <= 8:
        return True
    return bool(TAG_PATTERNS["percent_off"].search(line) or TAG_PATTERNS["bogo"].search(line))


def is_context_line(line: str) -> bool:
    return bool(VALIDITY_CONTEXT.search(line) or TIME_RANGE.search(line))


def context_prefix(lines: list[str], index: int) -> list[str]:
    prefix: list[str] = []
    for line in lines[max(0, index - 4) : index]:
        clean = normalize_line(line)
        if is_context_line(clean) or re.search(r"\b(?:happy hour|specials|daily specials|coupon|food|drinks?)\b", clean, re.I):
            prefix.append(clean)
    return prefix[-3:]


def context_suffix(lines: list[str], index: int) -> list[str]:
    suffix: list[str] = []
    for line in lines[index + 1 : min(len(lines), index + 8)]:
        clean = normalize_line(line)
        if not clean or any(pattern.search(clean) for pattern in NOISE_PATTERNS):
            continue
        if starts_new_deal(clean):
            break
        if len(clean) > 150 and not PROMO_CONTEXT.search(clean):
            continue
        if detect_tags(clean) or is_context_line(clean) or len(clean.split()) <= 14:
            suffix.append(clean)
        if len(suffix) >= 5:
            break
    return suffix


def candidate_windows(lines: list[str]) -> Iterable[Candidate]:
    seen: set[str] = set()
    for index, line in enumerate(lines):
        normalized = normalize_line(line)
        chunks = [normalized]
        if len(normalized) > 120:
            chunks.extend(re.split(r"(?<=[.!?])\s+", normalized))
        for chunk in chunks:
            summary = clean_summary(chunk)
            if not (4 <= len(summary) <= 180):
                continue
            details = context_prefix(lines, index) + context_suffix(lines, index)
            details = [item for item in details if item and item.lower() != summary.lower()]
            text = normalize_line(" ".join([summary, *details]))
            tags = detect_tags(text)
            key = re.sub(r"\W+", " ", text.lower()).strip()
            if key in seen or not tags or not is_quality_candidate(text, summary, tags):
                continue
            seen.add(key)
            yield {"text": text, "summary": summary, "details": dedupe(details)}


def clean_summary(text: str) -> str:
    summary = normalize_line(text)
    summary = re.sub(r"\s+\|\s+.*$", "", summary)
    summary = re.sub(r"\s{2,}", " ", summary)
    return summary[:180].strip()


def is_quality_candidate(text: str, summary: str, tags: list[str]) -> bool:
    lower = text.lower()
    if any(pattern.search(text) for pattern in NOISE_PATTERNS):
        return False
    if LOW_VALUE_SUMMARY.search(summary):
        return False
    if len(summary.split()) < 2 and not summary.startswith("$"):
        return False
    if len(text) > 360:
        return False
    if MENU_PRICE_CONTEXT.search(text) and not re.search(r"\b(?:off|free|happy hour|limited time|starting at|coupon)\b", lower):
        return False
    if "dollar_amount" in tags and not PROMO_CONTEXT.search(text):
        return False
    if tags == ["dollar_amount"] and not re.search(r"\b(?:off|each|starting at|special|deal|coupon|happy hour)\b", lower):
        return False
    if re.search(r"\b(?:corkage fee|additional side|add chicken|add salad|add soup)\b", lower):
        return False
    return any(tag in tags for tag in {"percent_off", "bogo", "happy_hour", "free", "deal_language", "dollar_amount"})


def extract_days(text: str) -> list[str]:
    lower = text.lower()
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

    if re.search(r"\b(?:daily|every day|everyday)\b", lower):
        return DAYS
    if re.search(r"\b(?:weekday|weekdays|monday\s*(?:-|to|thru|through|\u2013|\u2014)\s*friday|mon\s*(?:-|to|thru|through|\u2013|\u2014)\s*fri)\b", lower):
        return DAYS[:5]
    if re.search(r"\b(?:weekend|weekends)\b", lower):
        return DAYS[5:]

    found: list[str] = []
    day_pattern = r"(mon(?:day)?|tues?|tuesday|wed(?:nesday)?|thu(?:r|rs|rsday)?|thursday|fri(?:day)?|sat(?:urday)?|sun(?:day)?)"
    range_pattern = re.compile(rf"\b{day_pattern}\s*(?:-|to|thru|through|\u2013|\u2014)\s*{day_pattern}\b", re.I)
    for match in range_pattern.finditer(lower):
        start = aliases.get(match.group(1))
        end = aliases.get(match.group(2))
        if not start or not end:
            continue
        start_index = DAYS.index(start)
        end_index = DAYS.index(end)
        span = DAYS[start_index : end_index + 1] if start_index <= end_index else DAYS[start_index:] + DAYS[: end_index + 1]
        for day in span:
            if day not in found:
                found.append(day)

    for match in re.finditer(day_pattern, lower, re.I):
        day = aliases.get(match.group(1))
        if day and day not in found:
            found.append(day)
    return found


def normalize_time(hour: str, minute: str | None, period: str | None) -> str:
    if period and period.lower() == "close":
        return "close"
    suffix = f" {period.upper()}" if period else ""
    return f"{int(hour)}:{minute}{suffix}" if minute else f"{int(hour)}{suffix}"


def extract_time_window(text: str) -> str | None:
    match = TIME_RANGE.search(text)
    if not match:
        if re.search(r"\bafter\s+5\s*pm\b", text, re.I):
            return "After 5 PM"
        return None
    start_period = match.group(3) or (match.group(6) if match.group(6).lower() != "close" else None)
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


def validity_for(days: list[str], time_window: str | None) -> str:
    parts = [part for part in [day_label(days), time_window] if part]
    return ", ".join(parts) if parts else "Check source"


def deal_id(source: Source, candidate_text: str) -> str:
    stable_text = re.sub(r"\s+", " ", candidate_text.lower()).strip()
    digest = hashlib.sha1(f"{source.name}|{source.url}|{stable_text}".encode("utf-8")).hexdigest()
    return digest[:16]


def build_deal(source: Source, candidate: Candidate, now: datetime, existing: dict[str, dict]) -> dict:
    candidate_text = candidate["text"]
    tags = detect_tags(candidate_text)
    days = extract_days(candidate_text)
    time_window = extract_time_window(candidate_text)
    did = deal_id(source, candidate_text)
    previous = existing.get(did, {})
    return {
        "id": did,
        "restaurant": source.name,
        "city": source.city,
        "source_url": source.url,
        "source_notes": source.notes,
        "location": source.location,
        "candidate_text": candidate_text,
        "summary": candidate["summary"],
        "details": candidate["details"],
        "tags": tags,
        "categories": category_for(candidate_text),
        "applies_days": days,
        "time_window": time_window,
        "validity": validity_for(days, time_window),
        "first_seen": previous.get("first_seen") or iso(now),
        "last_seen": iso(now),
        "status": "active",
        "is_stale": False,
        "days_since_seen": 0,
    }


def aggregate_deals(source: Source, deals: list[dict], now: datetime, existing: dict[str, dict]) -> list[dict]:
    if source.options.get("exclude_menu_prices"):
        deals = [deal for deal in deals if has_explicit_discount(deal)]

    if source.options.get("aggregate_meal_deals"):
        meal_rows = [deal for deal in deals if re.search(r"\bmeal deals?\s*-?\s*starting at\s*\$?\d+", deal["candidate_text"], re.I)]
        others = [deal for deal in deals if deal not in meal_rows and has_explicit_discount(deal)]
        if meal_rows:
            text = "Meal Deals - Starting at $13"
            details = dedupe(extract_meal_details(meal_rows))[:8]
            candidate: Candidate = {"text": " ".join([text, *details]), "summary": text, "details": details}
            return [build_deal(source, candidate, now, existing), *others]
        return others

    compact: list[dict] = []
    seen_summaries: set[str] = set()
    for deal in deals:
        if not has_explicit_discount(deal) and source.options.get("strict"):
            continue
        key = re.sub(r"\W+", " ", deal["summary"].lower()).strip()
        if key in seen_summaries and not deal["summary"].startswith("$"):
            continue
        seen_summaries.add(key)
        compact.append(deal)
    return compact[: source.options.get("max_deals", 24)]


def has_explicit_discount(deal: dict) -> bool:
    text = deal.get("candidate_text", "")
    tags = set(deal.get("tags", []))
    return bool(tags.intersection({"percent_off", "bogo", "happy_hour", "free"}) or re.search(r"\b(?:off|coupon|limited time|starting at|happy hour|2-4-1|half price|with purchase|kids eat free)\b", text, re.I))


def extract_meal_details(meal_rows: list[dict]) -> list[str]:
    details: list[str] = []
    for deal in meal_rows:
        text = deal.get("candidate_text", "")
        for match in re.finditer(r"Meal Deals?\s*-?\s*Starting at\s*\$?\d+\s+([^$]+?)(?=\s+Meal Deals?|$)", text, re.I):
            item = normalize_line(match.group(1))
            item = re.sub(r"\s+\d{1,2}\.\d{2}\b.*$", "", item).strip()
            if item and len(item) < 80:
                details.append(item)
    return details or [deal.get("summary", "") for deal in meal_rows]


def crawl_source(source: Source, now: datetime, existing: dict[str, dict]) -> tuple[list[dict], dict]:
    page_html = fetch_html(source)
    lines = clean_text(page_html)
    deals = [build_deal(source, candidate, now, existing) for candidate in candidate_windows(lines)]
    deals = aggregate_deals(source, deals, now, existing)

    status = {
        "name": source.name,
        "city": source.city,
        "url": source.url,
        "notes": source.notes,
        "location": source.location,
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
        if not is_quality_candidate(deal.get("candidate_text", ""), deal.get("summary", ""), tags):
            continue
        carried = dict(deal)
        carried["status"] = "stale"
        carried["is_stale"] = True
        carried["days_since_seen"] = days_since_seen
        carried["stale_after_days"] = STALE_AFTER_DAYS
        stale_deals.append(carried)
    return stale_deals


def sort_deals(deals: list[dict]) -> list[dict]:
    return sorted(
        deals,
        key=lambda deal: (
            deal.get("status") != "active",
            deal.get("restaurant", ""),
            deal.get("city", ""),
            deal.get("validity", ""),
            deal.get("summary", ""),
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
                "notes": source.notes,
                "location": source.location,
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
