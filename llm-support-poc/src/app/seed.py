from __future__ import annotations

import random
from typing import List
from . import db


SUBJECTS = [
    "Can't log in to my account",
    "Billing question about last invoice",
    "App crashes when uploading a file",
    "Request: delete my data",
    "Feature request: dark mode",
    "Password reset link not working",
    "Research dataset export is incomplete",
    "Two-factor authentication issue",
    "Invoice INV-1042 shows duplicate line items",
    "Why was I charged twice on INV-2099?",
]

BODIES = [
    "Hi, I tried logging in but it says my password is incorrect. I already reset it twice.",
    "Hello, I was charged twice this month. Can you confirm and refund the duplicate charge? Invoice INV-2099.",
    "When I upload a PDF, the app freezes and then crashes. This happens every time.",
    "Please delete all my personal data associated with this email. Thanks.",
    "It would be great to have a dark mode for late-night work sessions.",
    "The password reset email arrives but the link says it has expired immediately.",
    "The export misses several files and the CSV looks truncated. Can you help?",
    "My 2FA code is never accepted even though the authenticator app is correct.",
    "On invoice INV-1042 I see two charges for the same dataset. Please clarify.",
    "I need a breakdown of invoice INV-1042, especially line item 3.",
]

EMAILS = [
    "alice@example.com",
    "bob@example.com",
    "chris@example.com",
    "dana@example.com",
    "eve@example.com",
    "fatima@example.com",
]

PRIORITIES = ["low", "normal", "high", "urgent"]


def seed_tickets(count: int = 6) -> List[int]:
    ids: List[int] = []
    for _ in range(count):
        subject = random.choice(SUBJECTS)
        body = random.choice(BODIES)
        requester_email = random.choice(EMAILS)
        priority = random.choices(PRIORITIES, weights=[25, 55, 15, 5])[0]
        tid = db.insert_ticket(subject=subject, requester_email=requester_email, body=body, priority=priority)
        ids.append(tid)
    return ids
