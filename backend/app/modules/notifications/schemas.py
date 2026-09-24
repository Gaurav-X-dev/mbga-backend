"""Pydantic schemas for the Notifications domain (API Reference §9)."""

from __future__ import annotations

from pydantic import BaseModel


class NotificationResponse(BaseModel):
    id: str
    type: str  # new_delivery | delivery_confirmed | order_updated | system
    title: str
    subtitle: str | None = None
    createdAt: str
    isRead: bool
