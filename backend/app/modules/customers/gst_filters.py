"""Read-only GST classification from the existing customer GSTIN."""
from typing import Annotated, Literal

from fastapi import Query
from sqlalchemy import func

from app.modules.customers.models import CustomerProfile


class GstFilters:
    def __init__(
        self,
        gst_status: Annotated[
            Literal["ALL", "GST", "NON_GST"], Query(alias="gstStatus")
        ] = "ALL",
    ):
        self.gst_status = gst_status

    def apply(self, statement):
        gstin = func.trim(func.coalesce(CustomerProfile.gst_number, ""))
        if self.gst_status == "GST":
            return statement.where(gstin != "")
        if self.gst_status == "NON_GST":
            return statement.where(gstin == "")
        return statement
