"""Merchant API channel."""
from fastapi import APIRouter

from app.modules.authentication.channel_router import build_channel_auth_router
from app.modules.authentication.constants import LoginChannel
from app.modules.constants.router import router as constants_router
from app.modules.customers.document_router import build_document_router
from app.modules.customers.kyc_router import router as kyc_router
from app.modules.customers.merchant_router import router as merchant_customers_router
from app.modules.customers.review_router import router as customer_review_router
from app.modules.delivery_users.router import router as delivery_users_router
from app.modules.expenses.router import router as expenses_router
from app.modules.notifications.router import build_notification_router
from app.modules.orders.router import build_order_router
from app.modules.pricing.router import customer_pricing_router, pricing_router

router = APIRouter()
router.include_router(build_channel_auth_router(LoginChannel.MERCHANT, "MERCHANT_LOGIN"))
router.include_router(delivery_users_router)
# Create / list / detail / eligibility, then the approve and reject routes that keep their
# existing paths. Both mount under /customers; the paths do not overlap.
router.include_router(merchant_customers_router)
router.include_router(customer_review_router)
router.include_router(kyc_router)
# Reviewers open customer documents, so this channel's document routes require the document
# review permission on top of the merchant session.
router.include_router(
    build_document_router(LoginChannel.MERCHANT, view_permissions=("customers.review", "customer_documents.review"))
)
# More -> Pricing -> Standard tab, and the Price Setting tab on a customer. The customer
# pricing routes also mount under /customers; their paths do not overlap with the
# detail, eligibility or review routes above.
router.include_router(pricing_router)
router.include_router(customer_pricing_router)
# Orders. The same handlers are mounted on the customer channel; only the actor and the
# required permissions differ (spec §6).
router.include_router(build_order_router(LoginChannel.MERCHANT))
# The bell: the in-app list behind the push notifications (spec §15).
router.include_router(build_notification_router(LoginChannel.MERCHANT))
# Expenses: the operational spend screens, with their own dynamic category list.
router.include_router(expenses_router)
# Public dropdown data. Mounted on both channels so each app calls its own base URL.
router.include_router(constants_router)
