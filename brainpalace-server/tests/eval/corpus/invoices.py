"""Invoice totalling helpers."""

from dataclasses import dataclass


@dataclass
class LineItem:
    description: str
    quantity: int
    unit_price_cents: int


def compute_invoice_total(items: list[LineItem], tax_rate: float) -> int:
    """Return the invoice grand total in cents, tax included.

    Sums quantity * unit_price for every line item, then applies the tax rate.
    The result is rounded to the nearest cent.
    """
    subtotal = sum(item.quantity * item.unit_price_cents for item in items)
    return round(subtotal * (1 + tax_rate))


def apply_discount(total_cents: int, percent_off: float) -> int:
    """Apply a percentage discount to a total expressed in cents."""
    return round(total_cents * (1 - percent_off / 100))
