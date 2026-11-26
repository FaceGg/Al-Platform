"""Admin endpoints for agent action audit + audit chain verification (S1, B2-08/E10)."""

from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session

from app.api.users import get_current_admin
from app.database import get_db
from app.models.user import User
from app.services.audit_chain import verify_all
from app.services.platform_audit import PlatformAuditIntent, record_platform_event

router = APIRouter(prefix="/api/admin", tags=["agent-audit"])


@router.get("/audit-chain/verify")
def verify_audit_chain(
    request: Request,
    db: Session = Depends(get_db),
    admin: User = Depends(get_current_admin),
):
    """两表审计链完整性校验（E10）：{table: {chained, unchained, complete, first_break}}。"""
    report = verify_all(db)
    record_platform_event(
        db,
        actor=admin,
        request=request,
        intent=PlatformAuditIntent(
            action="audit.chain.verify",
            resource_type="audit_chain",
            changes={"tables": sorted(report)},
        ),
        result="success",
    )
    db.commit()
    return report
