from datetime import UTC, datetime

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.business_catalogue import models, schemas
from app.shared.business.actor import BusinessActor
from app.shared.exceptions.api_error import ApiError


class BusinessCatalogueService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def list_customer_types(self, include_inactive: bool = False):
        query = select(models.CustomerTypeDefinition)
        if not include_inactive:
            query = query.where(models.CustomerTypeDefinition.is_active.is_(True))
        return list((await self.session.scalars(query.order_by(models.CustomerTypeDefinition.sort_order, models.CustomerTypeDefinition.label))).all())

    async def require_active_customer_type(self, code: str):
        row = await self._required(
            models.CustomerTypeDefinition, code, "CUSTOMER_TYPE_NOT_FOUND"
        )
        if not row.is_active:
            raise ApiError("CUSTOMER_TYPE_INACTIVE", 409, "Customer type is inactive.")
        return row

    async def default_customer_type(self):
        row = await self.session.scalar(
            select(models.CustomerTypeDefinition)
            .where(
                models.CustomerTypeDefinition.is_default.is_(True),
                models.CustomerTypeDefinition.is_active.is_(True),
            )
            .order_by(models.CustomerTypeDefinition.sort_order, models.CustomerTypeDefinition.code)
        )
        if row is None:
            raise ApiError("DEFAULT_CUSTOMER_TYPE_NOT_CONFIGURED", 409,
                           "Configure one active default customer type in the business catalogue.")
        return row

    async def create_customer_type(self, payload: schemas.CustomerTypeCreate, actor: BusinessActor):
        if await self.session.get(models.CustomerTypeDefinition, payload.code):
            raise ApiError("CATALOGUE_CODE_EXISTS", 409, "Customer type code already exists.")
        now = datetime.now(UTC)
        values = payload.model_dump(by_alias=False)
        if values.get("is_default"):
            await self._clear_default_customer_type()
        row = models.CustomerTypeDefinition(**values, is_active=True, is_protected=False,
            created_at=now, updated_at=now, updated_by_user_id=actor.user_id, updated_by_name=actor.display_name)
        self.session.add(row)
        await self.session.commit()
        return row

    async def update_customer_type(self, code: str, payload: schemas.CustomerTypeUpdate, actor: BusinessActor):
        row = await self._required(models.CustomerTypeDefinition, code, "CUSTOMER_TYPE_NOT_FOUND")
        changes = payload.model_dump(exclude_unset=True, by_alias=False)
        if changes.get("is_default") is True and (
            changes.get("is_active") is False
            or (not row.is_active and changes.get("is_active") is not True)
        ):
            raise ApiError(
                "DEFAULT_CUSTOMER_TYPE_MUST_BE_ACTIVE",
                422,
                "Only an active customer type can be selected as the default.",
            )
        if row.is_default and (
            changes.get("is_default") is False or changes.get("is_active") is False
        ):
            raise ApiError(
                "DEFAULT_CUSTOMER_TYPE_REQUIRED",
                409,
                "Select another active default customer type before disabling this one.",
            )
        if payload.is_default is True:
            await self._clear_default_customer_type(except_code=row.code)
        self._apply(row, payload, actor)
        await self.session.commit()
        return row

    async def _clear_default_customer_type(self, except_code: str | None = None) -> None:
        query = select(models.CustomerTypeDefinition).where(
            models.CustomerTypeDefinition.is_default.is_(True)
        )
        if except_code:
            query = query.where(models.CustomerTypeDefinition.code != except_code)
        for row in (await self.session.scalars(query)).all():
            row.is_default = False

    async def list_cylinders(self, include_inactive: bool = False):
        query = select(models.CylinderTypeDefinition)
        if not include_inactive:
            query = query.where(models.CylinderTypeDefinition.is_active.is_(True))
        return list((await self.session.scalars(query.order_by(models.CylinderTypeDefinition.sort_order, models.CylinderTypeDefinition.label))).all())

    async def create_cylinder(self, payload: schemas.CylinderTypeCreate, actor: BusinessActor):
        if await self.session.get(models.CylinderTypeDefinition, payload.code):
            raise ApiError("CATALOGUE_CODE_EXISTS", 409, "Cylinder type code already exists.")
        now = datetime.now(UTC)
        row = models.CylinderTypeDefinition(**payload.model_dump(by_alias=False), is_active=True, is_protected=False,
            created_at=now, updated_at=now, updated_by_user_id=actor.user_id, updated_by_name=actor.display_name)
        self.session.add(row)
        await self.session.commit()
        return row

    async def update_cylinder(self, code: str, payload: schemas.CylinderTypeUpdate, actor: BusinessActor):
        row = await self._required(models.CylinderTypeDefinition, code, "CYLINDER_TYPE_NOT_FOUND")
        self._apply(row, payload, actor)
        await self.session.commit()
        return row

    async def list_eligibility(self, customer_type_code: str):
        await self._required(models.CustomerTypeDefinition, customer_type_code, "CUSTOMER_TYPE_NOT_FOUND")
        query = select(models.CustomerTypeCylinder).where(
            models.CustomerTypeCylinder.customer_type_code == customer_type_code
        ).order_by(models.CustomerTypeCylinder.sort_order)
        return list((await self.session.scalars(query)).all())

    async def eligible_cylinders(self, customer_type_code: str):
        """Return active cylinder definitions and their customer-type limits.

        This is the runtime read used by orders and deliveries.  Keeping it here makes the
        catalogue tables the source of truth while the public APIs continue returning the
        same stable string codes consumed by the mobile apps.
        """
        customer_type = await self._required(
            models.CustomerTypeDefinition,
            customer_type_code,
            "CUSTOMER_TYPE_NOT_FOUND",
        )
        if not customer_type.is_active:
            raise ApiError("CUSTOMER_TYPE_INACTIVE", 409, "Customer type is inactive.")
        statement = (
            select(models.CustomerTypeCylinder, models.CylinderTypeDefinition)
            .join(
                models.CylinderTypeDefinition,
                models.CylinderTypeDefinition.code
                == models.CustomerTypeCylinder.cylinder_type_code,
            )
            .where(
                models.CustomerTypeCylinder.customer_type_code == customer_type.code,
                models.CustomerTypeCylinder.is_active.is_(True),
                models.CylinderTypeDefinition.is_active.is_(True),
            )
            .order_by(
                models.CustomerTypeCylinder.sort_order,
                models.CylinderTypeDefinition.sort_order,
                models.CylinderTypeDefinition.label,
            )
        )
        return list((await self.session.execute(statement)).all())

    async def require_active_cylinder(self, code: str):
        row = await self._required(
            models.CylinderTypeDefinition, code, "CYLINDER_TYPE_NOT_FOUND"
        )
        if not row.is_active:
            raise ApiError("CYLINDER_TYPE_INACTIVE", 409, "Cylinder type is inactive.")
        return row

    async def replace_eligibility(self, customer_type_code: str, payload: schemas.CylinderEligibilityReplace, actor: BusinessActor):
        await self._required(models.CustomerTypeDefinition, customer_type_code, "CUSTOMER_TYPE_NOT_FOUND")
        codes = [item.cylinder_type_code for item in payload.items]
        if len(codes) != len(set(codes)):
            raise ApiError("DUPLICATE_CYLINDER_TYPE", 422)
        found = set((await self.session.scalars(select(models.CylinderTypeDefinition.code).where(models.CylinderTypeDefinition.code.in_(codes)))).all())
        missing = sorted(set(codes) - found)
        if missing:
            raise ApiError("CYLINDER_TYPE_NOT_FOUND", 422, f"Unknown cylinder types: {', '.join(missing)}")
        await self.session.execute(delete(models.CustomerTypeCylinder).where(models.CustomerTypeCylinder.customer_type_code == customer_type_code))
        now = datetime.now(UTC)
        for item in payload.items:
            self.session.add(models.CustomerTypeCylinder(customer_type_code=customer_type_code,
                **item.model_dump(by_alias=False), updated_at=now, updated_by_user_id=actor.user_id))
        await self.session.commit()
        return await self.list_eligibility(customer_type_code)

    async def list_documents(self, include_inactive: bool = False):
        query = select(models.KycDocumentTypeDefinition)
        if not include_inactive:
            query = query.where(models.KycDocumentTypeDefinition.is_active.is_(True))
        return list((await self.session.scalars(query.order_by(models.KycDocumentTypeDefinition.sort_order, models.KycDocumentTypeDefinition.label))).all())

    async def create_document(self, payload: schemas.KycDocumentTypeCreate, actor: BusinessActor):
        if await self.session.get(models.KycDocumentTypeDefinition, payload.code):
            raise ApiError("CATALOGUE_CODE_EXISTS", 409, "Document type code already exists.")
        now = datetime.now(UTC)
        row = models.KycDocumentTypeDefinition(**payload.model_dump(by_alias=False), is_active=True, is_protected=False,
            created_at=now, updated_at=now, updated_by_user_id=actor.user_id)
        self.session.add(row)
        await self.session.commit()
        return row

    async def update_document(self, code: str, payload: schemas.KycDocumentTypeUpdate, actor: BusinessActor):
        row = await self._required(models.KycDocumentTypeDefinition, code, "DOCUMENT_TYPE_NOT_FOUND")
        self._apply(row, payload, actor)
        await self.session.commit()
        return row

    async def list_kyc_rules(self, customer_type_code: str):
        await self._required(models.CustomerTypeDefinition, customer_type_code, "CUSTOMER_TYPE_NOT_FOUND")
        query = select(models.CustomerTypeKycRule).where(
            models.CustomerTypeKycRule.customer_type_code == customer_type_code
        ).order_by(models.CustomerTypeKycRule.sort_order)
        return list((await self.session.scalars(query)).all())

    async def active_kyc_requirements(self, customer_type_code: str):
        customer_type = await self._required(
            models.CustomerTypeDefinition,
            customer_type_code,
            "CUSTOMER_TYPE_NOT_FOUND",
        )
        if not customer_type.is_active:
            raise ApiError("CUSTOMER_TYPE_INACTIVE", 409, "Customer type is inactive.")
        statement = (
            select(models.CustomerTypeKycRule, models.KycDocumentTypeDefinition)
            .join(
                models.KycDocumentTypeDefinition,
                models.KycDocumentTypeDefinition.code
                == models.CustomerTypeKycRule.document_type_code,
            )
            .where(
                models.CustomerTypeKycRule.customer_type_code == customer_type.code,
                models.CustomerTypeKycRule.is_active.is_(True),
                models.KycDocumentTypeDefinition.is_active.is_(True),
            )
            .order_by(
                models.CustomerTypeKycRule.sort_order,
                models.KycDocumentTypeDefinition.sort_order,
            )
        )
        return list((await self.session.execute(statement)).all())

    async def replace_kyc_rules(self, customer_type_code: str, payload: schemas.KycRulesReplace, actor: BusinessActor):
        await self._required(models.CustomerTypeDefinition, customer_type_code, "CUSTOMER_TYPE_NOT_FOUND")
        codes = [item.document_type_code for item in payload.items]
        if len(codes) != len(set(codes)):
            raise ApiError("DUPLICATE_DOCUMENT_TYPE", 422)
        found = set((await self.session.scalars(select(models.KycDocumentTypeDefinition.code).where(models.KycDocumentTypeDefinition.code.in_(codes)))).all())
        missing = sorted(set(codes) - found)
        if missing:
            raise ApiError("DOCUMENT_TYPE_NOT_FOUND", 422, f"Unknown document types: {', '.join(missing)}")
        await self.session.execute(delete(models.CustomerTypeKycRule).where(models.CustomerTypeKycRule.customer_type_code == customer_type_code))
        now = datetime.now(UTC)
        for item in payload.items:
            self.session.add(models.CustomerTypeKycRule(customer_type_code=customer_type_code,
                **item.model_dump(by_alias=False), updated_at=now, updated_by_user_id=actor.user_id))
        await self.session.commit()
        return await self.list_kyc_rules(customer_type_code)

    async def _required(self, model, key: str, code: str):
        row = await self.session.get(model, key.upper())
        if row is None:
            raise ApiError(code, 404)
        return row

    @staticmethod
    def _apply(row, payload, actor: BusinessActor) -> None:
        for name, value in payload.model_dump(exclude_unset=True, by_alias=False).items():
            setattr(row, name, value)
        row.updated_at = datetime.now(UTC)
        row.updated_by_user_id = actor.user_id
        if hasattr(row, "updated_by_name"):
            row.updated_by_name = actor.display_name
