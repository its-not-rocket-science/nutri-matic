"""Billing integration stub — Phase 3.2's public API platform needs a real
usage-metering *hook*, but not a live payment integration (explicitly out
of scope per nutri-matic-claude-prompts.txt: "Leave actual billing
integration as a stubbed interface").

Usage is genuinely metered regardless of billing: every /api/v1/* request
increments ApiKey.requests_this_period and is checked against
ApiKey.quota_limit (see api_keys.py::get_api_key_user) — that part is real
and enforced today, with or without a billing provider behind it. What's
stubbed is turning that metered usage into an actual invoice/charge.

To wire in a real billing provider later (Stripe usage records, etc.):
implement BillingProvider and set the module-level `billing_provider`
below to an instance of it — nothing else in the request path needs to
change, since get_api_key_user already calls record_usage() on every
successful request.
"""

from typing import Protocol

from .models import ApiKey, User


class BillingProvider(Protocol):
    def record_usage(self, user: User, api_key: ApiKey, endpoint: str) -> None:
        """Called once per successful /api/v1/* request, after quota
        enforcement has already passed. Must not raise — a billing-provider
        failure should never block or fail an otherwise-successful API
        response; a real implementation should catch and log its own
        errors internally."""
        ...


class NoOpBillingProvider:
    """The only provider that exists today. Usage is still tracked (see
    module docstring) — this just never turns it into a bill."""

    def record_usage(self, user: User, api_key: ApiKey, endpoint: str) -> None:
        return None


billing_provider: BillingProvider = NoOpBillingProvider()
