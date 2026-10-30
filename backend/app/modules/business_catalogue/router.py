from typing import Annotated

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.authentication.constants import LoginChannel
from app.modules.business_catalogue import schemas
from app.modules.business_catalogue.service import BusinessCatalogueService
from app.modules.customers.dependencies import ActorDep
from app.shared.authorization.dependencies import require_login_channel, require_permission
from app.shared.database.session import get_db_session
from app.shared.exceptions.openapi import error_responses

SessionDep = Annotated[AsyncSession, Depends(get_db_session)]


def build_catalogue_router(channel: LoginChannel) -> APIRouter:
    router = APIRouter(
        prefix="/catalogue",
        tags=[f"{channel.value.lower()}-business-catalogue"],
        dependencies=[Depends(require_login_channel(channel))],
    )
    view = Depends(require_permission("catalogue.view"))
    manage = Depends(require_permission("catalogue.manage"))

    @router.get("/customer-types", response_model=list[schemas.CustomerTypeView], dependencies=[view])
    async def customer_types(session: SessionDep, include_inactive: bool = Query(False, alias="includeInactive")):
        return await BusinessCatalogueService(session).list_customer_types(include_inactive)

    @router.post("/customer-types", response_model=schemas.CustomerTypeView, status_code=201,
                 dependencies=[manage], responses=error_responses(401, 403, 409, 422))
    async def create_customer_type(payload: schemas.CustomerTypeCreate, session: SessionDep, actor: ActorDep):
        return await BusinessCatalogueService(session).create_customer_type(payload, actor)

    @router.patch("/customer-types/{code}", response_model=schemas.CustomerTypeView,
                  dependencies=[manage], responses=error_responses(401, 403, 404, 422))
    async def update_customer_type(code: str, payload: schemas.CustomerTypeUpdate, session: SessionDep, actor: ActorDep):
        return await BusinessCatalogueService(session).update_customer_type(code, payload, actor)

    @router.get("/cylinder-types", response_model=list[schemas.CylinderTypeView], dependencies=[view])
    async def cylinder_types(session: SessionDep, include_inactive: bool = Query(False, alias="includeInactive")):
        rows = await BusinessCatalogueService(session).list_cylinders(include_inactive)
        return [schemas.CylinderTypeView.model_validate({
            **{name: getattr(row, name) for name in schemas.CylinderTypeCreate.model_fields},
            "is_active": row.is_active,
            "is_protected": row.is_protected,
            "default_unit_price": row.default_base_rate + row.default_markup,
        }) for row in rows]

    @router.post("/cylinder-types", response_model=schemas.CylinderTypeView, status_code=201,
                 dependencies=[manage], responses=error_responses(401, 403, 409, 422))
    async def create_cylinder(payload: schemas.CylinderTypeCreate, session: SessionDep, actor: ActorDep):
        row = await BusinessCatalogueService(session).create_cylinder(payload, actor)
        return schemas.CylinderTypeView.model_validate({**payload.model_dump(), "is_active": True,
            "is_protected": False, "default_unit_price": row.default_base_rate + row.default_markup})

    @router.patch("/cylinder-types/{code}", response_model=schemas.CylinderTypeView,
                  dependencies=[manage], responses=error_responses(401, 403, 404, 422))
    async def update_cylinder(code: str, payload: schemas.CylinderTypeUpdate, session: SessionDep, actor: ActorDep):
        row = await BusinessCatalogueService(session).update_cylinder(code, payload, actor)
        data = {name: getattr(row, name) for name in schemas.CylinderTypeCreate.model_fields}
        return schemas.CylinderTypeView.model_validate({**data, "is_active": row.is_active,
            "is_protected": row.is_protected, "default_unit_price": row.default_base_rate + row.default_markup})

    @router.get("/customer-types/{code}/cylinders", response_model=list[schemas.CylinderEligibilityItem], dependencies=[view])
    async def eligibility(code: str, session: SessionDep):
        return await BusinessCatalogueService(session).list_eligibility(code.upper())

    @router.put("/customer-types/{code}/cylinders", response_model=list[schemas.CylinderEligibilityItem],
                dependencies=[manage], responses=error_responses(401, 403, 404, 422))
    async def replace_eligibility(code: str, payload: schemas.CylinderEligibilityReplace, session: SessionDep, actor: ActorDep):
        return await BusinessCatalogueService(session).replace_eligibility(code.upper(), payload, actor)

    @router.get("/kyc-document-types", response_model=list[schemas.KycDocumentTypeView], dependencies=[view])
    async def document_types(session: SessionDep, include_inactive: bool = Query(False, alias="includeInactive")):
        return await BusinessCatalogueService(session).list_documents(include_inactive)

    @router.post("/kyc-document-types", response_model=schemas.KycDocumentTypeView, status_code=201,
                 dependencies=[manage], responses=error_responses(401, 403, 409, 422))
    async def create_document(payload: schemas.KycDocumentTypeCreate, session: SessionDep, actor: ActorDep):
        return await BusinessCatalogueService(session).create_document(payload, actor)

    @router.patch("/kyc-document-types/{code}", response_model=schemas.KycDocumentTypeView,
                  dependencies=[manage], responses=error_responses(401, 403, 404, 422))
    async def update_document(code: str, payload: schemas.KycDocumentTypeUpdate, session: SessionDep, actor: ActorDep):
        return await BusinessCatalogueService(session).update_document(code, payload, actor)

    @router.get("/customer-types/{code}/kyc-rules", response_model=list[schemas.KycRuleItem], dependencies=[view])
    async def kyc_rules(code: str, session: SessionDep):
        return await BusinessCatalogueService(session).list_kyc_rules(code.upper())

    @router.put("/customer-types/{code}/kyc-rules", response_model=list[schemas.KycRuleItem],
                dependencies=[manage], responses=error_responses(401, 403, 404, 422))
    async def replace_kyc_rules(code: str, payload: schemas.KycRulesReplace, session: SessionDep, actor: ActorDep):
        return await BusinessCatalogueService(session).replace_kyc_rules(code.upper(), payload, actor)

    return router
