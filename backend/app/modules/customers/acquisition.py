"""Read-only acquisition reporting using existing creation audit events."""
from datetime import date
from typing import Annotated

from fastapi import Query
from sqlalchemy import func, or_, select

from app.modules.audit_logs.models import AuditLog
from app.modules.customers.models import CustomerProfile
from app.modules.users.models import User
from app.modules.merchants.models import MerchantUser
from app.shared.date_time.business_calendar import business_day_window
from app.shared.exceptions.api_error import ApiError


def creator_id():
    return (select(AuditLog.actor_user_id).where(
        AuditLog.entity_type == "customer_profile",
        AuditLog.entity_id == CustomerProfile.id,
        AuditLog.event_type == "customer.created_by_staff",
    ).order_by(AuditLog.created_at, AuditLog.id).limit(1)
        .correlate(CustomerProfile).scalar_subquery())


class AcquisitionFilters:
    def __init__(self,
        employee: Annotated[str | None, Query(max_length=36)] = None,
        date_from: Annotated[date | None, Query(alias="dateFrom")] = None,
        date_to: Annotated[date | None, Query(alias="dateTo")] = None,
    ):
        if date_from and date_to and date_from > date_to:
            raise ApiError("VALIDATION_ERROR", 422, "Start date must be on or before end date.")
        if date_to == date.max:
            raise ApiError("VALIDATION_ERROR", 422, "End date is outside the supported range.")
        self.employee, self.date_from, self.date_to = employee, date_from, date_to

    def apply(self, statement):
        if self.employee:
            statement = statement.where(creator_id() == self.employee)
        registered = func.coalesce(CustomerProfile.registered_at, CustomerProfile.created_at)
        if self.date_from:
            statement = statement.where(registered >= business_day_window(self.date_from)[0])
        if self.date_to:
            statement = statement.where(registered < business_day_window(self.date_to)[1])
        return statement


async def employees(session, merchant_id):
    creators = select(creator_id().label("employee_id")).where(
        CustomerProfile.merchant_id == merchant_id).subquery()
    # Include staff before their first acquisition, while keeping historical creators.
    staff = select(MerchantUser.user_id).where(
        MerchantUser.merchant_id == merchant_id, MerchantUser.status == "ACTIVE"
    )
    rows = (await session.execute(select(User.id, User.full_name)
        .where(or_(User.id.in_(select(creators.c.employee_id)), User.id.in_(staff)))
        .order_by(User.full_name, User.id))).all()
    return [{"value": row.id, "label": row.full_name or row.id} for row in rows]


async def attribute_employees(session, profiles, items):
    if not profiles:
        return
    rows = (await session.execute(
        select(CustomerProfile.id, creator_id().label("employee_id"))
        .where(CustomerProfile.id.in_([profile.id for profile in profiles]))
    )).all()
    identities = {row.id: row.employee_id for row in rows}
    ids = {value for value in identities.values() if value}
    users = (await session.execute(select(User.id, User.full_name).where(User.id.in_(ids)))).all() if ids else []
    names = {row.id: row.full_name for row in users}
    for item in items:
        item.employee_id = identities.get(item.id)
        item.employee_name = names.get(item.employee_id)
