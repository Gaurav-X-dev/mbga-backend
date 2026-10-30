"""Private, tenant-scoped expense receipts."""
from uuid import uuid4
from datetime import UTC, datetime
from app.shared.storage.file_types import detect_content_type, JPEG, PNG, PDF
from app.shared.business.audit import BusinessAuditor
from app.shared.exceptions.api_error import ApiError


async def save_receipt(service, storage, expense_id, file):
    expense, _category = await service._owned_expense(expense_id)
    content = await file.read(5 * 1024 * 1024 + 1)
    media = detect_content_type(content[:16], file.filename).content_type
    if len(content) > 5 * 1024 * 1024 or media not in {JPEG, PNG, PDF}:
        raise ApiError("VALIDATION_ERROR", 422, "Upload a JPG, PNG or PDF receipt up to 5 MB.")
    key = f"expenses/{service.merchant_id}/{expense.id}/{uuid4()}"
    async def chunks():
        yield content
    await storage.save(key, chunks())
    try:
        expense.receipt_storage_key = key
        expense.receipt_content_type = media
        expense.updated_at = datetime.now(UTC)
        await BusinessAuditor(service.session).record("expense.receipt_updated", actor=service.actor,
            entity_type="expense", entity_id=expense.id, message="Expense receipt uploaded or replaced")
        await service.session.commit()
    except BaseException:
        await storage.delete(key)
        raise
    # Old receipts are retained privately for audit; no public storage URL is exposed.
    return {"hasReceipt": True}


async def read_receipt(service, storage, expense_id):
    expense, _category = await service._owned_expense(expense_id)
    if not expense.receipt_storage_key:
        raise ApiError("NOT_FOUND", 404)
    try:
        return storage.open(expense.receipt_storage_key), expense.receipt_content_type
    except FileNotFoundError:
        raise ApiError("NOT_FOUND", 404) from None
