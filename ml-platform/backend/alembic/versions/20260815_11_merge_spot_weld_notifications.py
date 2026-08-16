"""Merge spot-weld quality and security notification migration heads.

Revision ID: 20260815_11
Revises: 20260720_10_security_notifications, 20260730_09
Create Date: 2026-08-15
"""

from collections.abc import Sequence


revision = "20260815_11"
down_revision: tuple[str, str] = (
    "20260720_10_security_notifications",
    "20260730_09",
)
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
