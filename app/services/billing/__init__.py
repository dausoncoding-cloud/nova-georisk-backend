"""Platform subscriptions: plan catalogue, credit ledger, and submission charging.

Design: docs/PLATFORM_SUBSCRIPTIONS_PLAN.md. Everything that writes the ledger runs under a row lock
on the subscription (`ledger.lock_subscription`), and every entry has a unique idempotency key.
"""
