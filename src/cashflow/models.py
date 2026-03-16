from dataclasses import dataclass
from datetime import date
from typing import Optional

@dataclass
class ParsedTransaction:
    date: date
    amount: float
    description: str
    merchant: str
    source_id: str
    source_type: str
    account_name: str
    order_number: Optional[str] = None
    who: str = "shared"
