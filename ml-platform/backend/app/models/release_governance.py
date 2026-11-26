"""Release governance models (补齐路线第二批 S2b, B2-09/02/03/G2/G3).

影子对照报告（E14 不可变）/ 发布门禁检查留档（B2-03 随发布单归档、进证据链）/
发布预授权（G2 授权人≠申请人、质量门指纹）/ rollout 服务端回执（G3 回执契约
四要素：版本、产物摘要、打分量、时间窗——第四批盒端接入同一契约）。
DeploymentTarget.role 扩 'challenger'（B2-09 别名在既有部署目标机制上扩展，C18）。
"""
import uuid

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    Column,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    JSON,
    String,
    func,
)
from sqlalchemy.dialects.postgresql import UUID

from app.database import Base

SHADOW_SAMPLE_SOURCES = ("random_sample", "traffic_mirror")
CHECK_VERDICTS = ("passed", "failed", "not_applicable")
PREAUTH_STATUSES = ("active", "revoked")
RECEIPT_STATUSES = ("valid", "digest_mismatch")


class ShadowComparison(Base):
    __tablename__ = "shadow_comparisons"
    __table_args__ = (
        CheckConstraint(
            "sample_source IN ('random_sample', 'traffic_mirror')",
            name="ck_shadow_comparisons_source",
        ),
        Index("ix_shadow_comparisons_deployment", "deployment_id", "created_at"),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    project_id = Column(
        UUID(as_uuid=True),
        ForeignKey("projects.id", ondelete="CASCADE"),
        nullable=False,
    )
    deployment_id = Column(UUID(as_uuid=True), nullable=True)
    champion_version_id = Column(UUID(as_uuid=True), nullable=True)
    challenger_version_id = Column(UUID(as_uuid=True), nullable=True)
    window_start = Column(DateTime, nullable=True)
    window_end = Column(DateTime, nullable=True)
    sample_source = Column(String(16), nullable=False)
    sample_count = Column(Integer, nullable=False, default=0)
    agreement_rate = Column(Float, nullable=True)
    detail = Column(JSON, nullable=False, default=dict)
    report_fingerprint = Column(String(64), nullable=False)
    created_by_id = Column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    created_at = Column(DateTime, nullable=False, server_default=func.now())


class ReleaseCheck(Base):
    __tablename__ = "release_checks"
    __table_args__ = (
        CheckConstraint(
            "verdict IN ('passed', 'failed', 'not_applicable')",
            name="ck_release_checks_verdict",
        ),
        Index("ix_release_checks_approval", "approval_id"),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    approval_id = Column(
        UUID(as_uuid=True),
        ForeignKey("approval_requests.id", ondelete="CASCADE"),
        nullable=False,
    )
    check_key = Column(String(64), nullable=False)
    threshold = Column(JSON, nullable=True)
    observed = Column(JSON, nullable=True)
    verdict = Column(String(16), nullable=False)
    detail = Column(JSON, nullable=True)
    created_at = Column(DateTime, nullable=False, server_default=func.now())


class ReleasePreauthorization(Base):
    __tablename__ = "release_preauthorizations"
    __table_args__ = (
        CheckConstraint(
            "status IN ('active', 'revoked')",
            name="ck_release_preauth_status",
        ),
        Index("ix_release_preauth_project", "project_id", "status"),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    project_id = Column(
        UUID(as_uuid=True),
        ForeignKey("projects.id", ondelete="CASCADE"),
        nullable=False,
    )
    deployment_id = Column(UUID(as_uuid=True), nullable=True)
    station_id = Column(UUID(as_uuid=True), nullable=True)
    acceptance_gates_fingerprint = Column(String(64), nullable=False)
    valid_from = Column(DateTime, nullable=False, server_default=func.now())
    expires_at = Column(DateTime, nullable=False)
    max_releases = Column(Integer, nullable=False, default=1)
    releases_used = Column(Integer, nullable=False, default=0)
    status = Column(String(16), nullable=False, default="active")
    granted_by_id = Column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    note = Column(String(256), nullable=True)
    created_at = Column(DateTime, nullable=False, server_default=func.now())


class RolloutReceipt(Base):
    __tablename__ = "rollout_receipts"
    __table_args__ = (
        CheckConstraint(
            "status IN ('valid', 'digest_mismatch')",
            name="ck_rollout_receipts_status",
        ),
        Index("ix_rollout_receipts_rollout", "rollout_id", "reported_at"),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    project_id = Column(
        UUID(as_uuid=True),
        ForeignKey("projects.id", ondelete="CASCADE"),
        nullable=False,
    )
    rollout_id = Column(UUID(as_uuid=True), nullable=False)
    revision_id = Column(UUID(as_uuid=True), nullable=True)
    routing_key = Column(String(256), nullable=True)
    effective_alias = Column(String(256), nullable=False)
    scored_count = Column(BigInteger, nullable=False, default=0)
    artifact_digest = Column(String(64), nullable=True)
    window_start = Column(DateTime, nullable=True)
    window_end = Column(DateTime, nullable=True)
    status = Column(String(16), nullable=False)
    reported_by_id = Column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    reported_at = Column(DateTime, nullable=False, server_default=func.now())
