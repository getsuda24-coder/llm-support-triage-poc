from __future__ import annotations

from . import db


def seed_invoices() -> list[int]:
    invoices = [
        {
            "invoice_id": "INV-1042",
            "customer_email": "alice@example.com",
            "lines": [
                {"item": "Dataset export (Pro)", "qty": 1, "unit_price": 120.00},
                {"item": "Compute credits", "qty": 50, "unit_price": 0.50},
                {"item": "Support plan (monthly)", "qty": 1, "unit_price": 49.00},
            ],
            "currency": "USD",
            "status": "paid",
        },
        {
            "invoice_id": "INV-2099",
            "customer_email": "bob@example.com",
            "lines": [
                {"item": "Team seats", "qty": 3, "unit_price": 89.00},
                {"item": "Storage add-on", "qty": 1, "unit_price": 25.00},
            ],
            "currency": "USD",
            "status": "open",
        },
    ]

    ids: list[int] = []
    for inv in invoices:
        total = sum(l["qty"] * l["unit_price"] for l in inv["lines"])
        text = (
            f"Invoice {inv['invoice_id']} for {inv['customer_email']}\n"
            f"Status: {inv['status']}\n"
            f"Currency: {inv['currency']}\n"
            f"Line items:\n"
            + "\n".join([f"- {l['item']}: qty={l['qty']} unit={l['unit_price']:.2f}" for l in inv["lines"]])
            + f"\nTotal: {total:.2f} {inv['currency']}\n"
            "Policy: refunds are possible for duplicate charges; verify usage and billing period before confirming."
        )
        doc_id = db.kb_add_doc(
            source="seed",
            title=f"Invoice {inv['invoice_id']}",
            text=text,
            metadata={
                "invoice_id": inv["invoice_id"],
                "customer_email": inv["customer_email"],
                "total": total,
                "currency": inv["currency"],
            },
        )
        ids.append(doc_id)
    return ids
