from fastapi import APIRouter

from app.modules.audit_logs.router import router as audit_logs_router
from app.modules.authentication.admin_sessions_router import router as login_sessions_router
from app.modules.authentication.channel_router import build_channel_auth_router
from app.modules.authentication.constants import LoginChannel
from app.modules.customers.admin_kyc_router import router as customer_kyc_router
from app.modules.dashboard.analytics_router import router as dashboard_analytics_router
from app.modules.dashboard.router import router as dashboard_router
from app.modules.merchants.router import router as merchants_router
from app.modules.permissions.router import router as permissions_router
from app.modules.roles.router import router as roles_router
from app.modules.users.router import router as users_router

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
router.include_router(audit_logs_router)
# Who is signed in, across every channel, and the ability to end a session.
router.include_router(login_sessions_router)
# Customer KYC across the whole network, read-only: the approve/reject decision stays with
# the merchant that holds the customer relationship.
router.include_router(customer_kyc_router)
