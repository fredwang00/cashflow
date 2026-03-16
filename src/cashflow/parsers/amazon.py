import re
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path


@dataclass
class AmazonItem:
    name: str
    is_subscribe_save: bool = False
    delivery_frequency: str | None = None


@dataclass
class AmazonOrder:
    order_number: str
    order_date: 'datetime.date'
    total: float
    account: str  # "fred" or "wife"
    items: list[AmazonItem] = field(default_factory=list)


ORDER_NUMBER_RE = re.compile(r"Order #\s*(\d{3}-\d{7}-\d{7})")
TOTAL_RE = re.compile(r"^\$[\d,]+\.\d{2}$")
DATE_RE = re.compile(r"^(January|February|March|April|May|June|July|August|September|October|November|December)\s+\d{1,2},\s+\d{4}$")
AUTO_DELIVERED_RE = re.compile(r"Auto-delivered:\s+(.+)")

SKIP_PATTERNS = [
    "Buy it again", "Track package", "View or edit order",
    "View your Subscribe & Save", "Ask Product Question",
    "Write a product review", "Leave seller feedback",
    "Return or replace items", "View your item",
    "Share gift receipt", "Get product support",
    "Add a protection plan", "Replace item",
]

SKIP_PREFIXES = [
    "Your package was", "Delivered ", "Arriving ", "Now arriving ",
    "Previously expected", "Return or replace items:",
    "Return items:", "Return window closed",
    "Return eligibility", "Purchased at",
    "The brand image", "Applied",
    "Gift Card balance", "View order details",
    "Your order was cancelled",
]


def _normalize_for_dedup(text: str) -> str:
    """Normalize dashes and whitespace for duplicate detection.

    Amazon shows item names twice: display text uses em/en dashes,
    accessible text uses regular hyphens. Normalize so they match.
    """
    return text.replace("\u2013", "-").replace("\u2014", "-").replace("\u2012", "-").strip()


def _is_ui_chrome(line: str) -> bool:
    """Check if a line is UI navigation/chrome rather than an item name."""
    stripped = line.strip()
    if not stripped:
        return True
    if stripped in SKIP_PATTERNS:
        return True
    for prefix in SKIP_PREFIXES:
        if stripped.startswith(prefix):
            return True
    if ORDER_NUMBER_RE.match(stripped):
        return True
    if TOTAL_RE.match(stripped):
        return True
    if DATE_RE.match(stripped):
        return True
    if AUTO_DELIVERED_RE.match(stripped):
        return True
    if stripped in ("Order placed", "Total", "Ship to", "Cancelled",
                    "Your Orders", "Search all orders", "Search Orders",
                    "Orders Buy Again Not Yet Shipped Digital Orders Amazon Pay",
                    "Ordered by", "Fred", "PICKUP AT"):
        return True
    if re.match(r"^\d+ orders placed in\s*$", stripped):
        return True
    if re.match(r"^\d{4}$", stripped):
        return True
    if stripped.startswith("Fred Wang") or stripped.startswith("Virginia Beach"):
        return True
    if stripped == "--":
        return True
    return False


def parse_amazon_orders(path: Path, default_account: str = "fred") -> list[AmazonOrder]:
    """Parse an Amazon 'Your Orders' screen scrape into structured orders.

    Skips cancelled orders. Detects Subscribe & Save and wife's account
    (via 'Ordered by' marker).
    """
    lines = path.read_text(encoding="utf-8").splitlines()

    orders = []
    i = 0

    while i < len(lines):
        line = lines[i].strip()

        if line != "Order placed":
            i += 1
            continue

        i += 1
        if i >= len(lines):
            break
        date_str = lines[i].strip()
        date_match = DATE_RE.match(date_str)
        if not date_match:
            continue
        order_date = datetime.strptime(date_str, "%B %d, %Y").date()
        i += 1

        total = 0.0
        order_number = None
        is_cancelled = False
        account = default_account
        items = []
        seen_item_names = set()

        while i < len(lines):
            scan_line = lines[i].strip()

            if scan_line == "Order placed":
                break

            if scan_line == "--":
                i += 1
                break

            if TOTAL_RE.match(scan_line):
                total = float(scan_line.replace("$", "").replace(",", ""))
                i += 1
                continue

            order_match = ORDER_NUMBER_RE.match(scan_line)
            if order_match:
                order_number = order_match.group(1)
                i += 1
                continue

            if scan_line == "Cancelled":
                is_cancelled = True
                i += 1
                continue

            if scan_line == "Ordered by":
                account = "wife"
                i += 1
                continue

            auto_match = AUTO_DELIVERED_RE.match(scan_line)
            if auto_match:
                if items:
                    items[-1].is_subscribe_save = True
                    items[-1].delivery_frequency = auto_match.group(1)
                i += 1
                continue

            # Item name detection with dash normalization for dedup
            normalized = _normalize_for_dedup(scan_line)
            if not _is_ui_chrome(scan_line) and normalized not in seen_item_names:
                seen_item_names.add(normalized)
                items.append(AmazonItem(name=scan_line))
            elif normalized in seen_item_names:
                pass  # Duplicate (accessible name)

            i += 1

        if order_number and not is_cancelled:
            orders.append(AmazonOrder(
                order_number=order_number,
                order_date=order_date,
                total=total,
                account=account,
                items=items,
            ))

    return orders
