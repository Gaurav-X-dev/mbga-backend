from fastapi import APIRouter

from app.modules.audit_logs.router import router as audit_logs_router
from app.modules.authentication.admin_sessions_router import router as login_sessions_router
from app.modules.authentication.channel_router import build_channel_auth_router
from app.modules.authentication.constants import LoginChannel
from app.modules.constants.router import router as constants_router
from app.modules.credit.router import router as credit_router
from app.modules.customers.admin_kyc_router import router as customer_kyc_router
from app.modules.customers.admin_merchant_router import router as merchant_customers_router
from app.modules.customers.admin_review_router import router as customer_review_router
from app.modules.customers.document_router import build_document_router
from app.modules.dashboard.analytics_router import router as dashboard_analytics_router
from app.modules.dashboard.router import router as dashboard_router
from app.modules.deliveries.admin_router import router as deliveries_router
from app.modules.delivery_users.admin_router import router as delivery_users_router
from app.modules.expenses.admin_router import router as expenses_router
from app.modules.inventory.admin_router import router as inventory_router
from app.modules.locations.admin_router import router as postal_locations_router
from app.modules.locations.router import router as locations_router
from app.modules.merchants.router import router as merchants_router
from app.modules.notifications.router import build_notification_router
from app.modules.orders.router import build_order_router
from app.modules.payments.router import build_payment_router
from app.modules.permissions.router import router as permissions_router
from app.modules.platform_settings.router import router as platform_settings_router
from app.modules.pricing.admin_router import customer_pricing_router, pricing_router
from app.modules.reports.admin_router import router as reports_router
from app.modules.roles.router import router as roles_router
from app.modules.tasks.admin_router import router as tasks_router
from app.modules.tasks.admin_router import team_router
from app.modules.users.router import router as users_router
from app.modules.vehicles.admin_router import router as vehicles_router

router = APIRouter()
router.include_router(build_channel_auth_router(LoginChannel.ADMIN, "ADMIN_LOGIN"))
router.include_router(dashboard_router)
# The chart series behind the dashboard. Its own router so the summary tiles stay a cheap
# call that a slow aggregate can never hold up.
router.include_router(dashboard_analytics_router)
router.include_router(merchants_router)
router.include_router(users_router)
router.include_router(roles_router)
router.include_router(permissions_router)
router.include_router(platform_settings_router)
router.include_router(credit_router)
router.include_router(audit_logs_router)
router.include_router(reports_router)
router.include_router(build_order_router(LoginChannel.ADMIN))
router.include_router(merchant_customers_router)
router.include_router(customer_review_router)
router.include_router(
    build_document_router(
        LoginChannel.ADMIN,
        view_permissions=("customers.review", "customer_documents.review"),
    )
)
router.include_router(pricing_router)
router.include_router(customer_pricing_router)
router.include_router(delivery_users_router)
router.include_router(vehicles_router)
router.include_router(build_payment_router(LoginChannel.ADMIN))
router.include_router(build_notification_router(LoginChannel.ADMIN))
router.include_router(expenses_router)
router.include_router(inventory_router)
router.include_router(deliveries_router)
router.include_router(team_router)
router.include_router(tasks_router)
router.include_router(constants_router)
router.include_router(locations_router)
router.include_router(postal_locations_router)
# Who is signed in, across every channel, and the ability to end a session.
router.include_router(login_sessions_router)
# Customer KYC across the whole network, read-only: the approve/reject decision stays with
# the merchant that holds the customer relationship.
router.include_router(customer_kyc_router)
