"""Batch the current KYC file sides without changing the legacy primary-document fields."""
from sqlalchemy import select
from app.modules.customers.models import CustomerDocument
from app.modules.customers.v2_models import CustomerDocumentFileV2
from app.modules.customers.business_schemas import KycDocumentFileResponse


async def load_document_files(session, primary_documents):
    if not primary_documents:
        return {}
    customer_ids={document.customer_id for document in primary_documents if document.customer_id}
    mappings=list(await session.scalars(select(CustomerDocumentFileV2).where(
        CustomerDocumentFileV2.customer_id.in_(customer_ids),
        CustomerDocumentFileV2.superseded_at.is_(None)).order_by(CustomerDocumentFileV2.sort_order,CustomerDocumentFileV2.id)))
    if not mappings:
        return {}
    files={document.file_id:document for document in await session.scalars(select(CustomerDocument).where(
        CustomerDocument.file_id.in_([mapping.file_id for mapping in mappings])))}
    groups={}
    for mapping in mappings:
        groups.setdefault((mapping.customer_id,mapping.document_type),[]).append(mapping)
    result={}
    for primary in primary_documents:
        group=groups.get((primary.customer_id,primary.document_type),[])
        # A V1 replacement must not revive an older V2 front/back pair.
        if not any(mapping.file_id==primary.file_id and mapping.is_primary for mapping in group):
            continue
        current=[]
        for mapping in group:
            document=files.get(mapping.file_id)
            if document is None or document.document_type!=primary.document_type or document.merchant_id!=primary.merchant_id:
                continue
            current.append(KycDocumentFileResponse(fileId=document.file_id,fileName=document.original_filename,
                fileSize=document.file_size,contentType=document.mime_type,side=mapping.side,
                source=mapping.source,sortOrder=mapping.sort_order))
        result[primary.id]=current
    return result
