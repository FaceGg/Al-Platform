"""QMS compliance models (补齐路线第三批, B3-01~B3-10, 技术方案 §1).

T1 闭环内聚件（NCR/CAPA、8D、案例、知识库、追溯）+ T2 报告与控制
（质量报告、动态控制计划）+ T3 工具件（MSA、FMEA、供应商 IQC→SCAR）。
全部带 project_id 归属；领域口径（IATF 16949/8D/MSA）标注待质量专家评审。
"""
import uuid

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Column,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    JSON,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import UUID

from app.database import Base

NCR_STAGES = ("draft", "analysis", "action", "verification", "closed", "rejected")
CASE_STATUSES = ("open", "monitoring", "closed")
REPORT_PERIODS = ("daily", "weekly", "monthly")
PLAN_STATUSES = ("active", "archived")
GRR_GRADES = ("acceptable", "conditional", "unacceptable")
SUPPLIER_STATUSES = ("active", "disabled")


class QmsNcrCapa(Base):
    __tablename__ = "qms_ncr_capas"
    __table_args__ = (
        UniqueConstraint("project_id", "code", name="uq_qms_ncr_project_code"),
        CheckConstraint(
            "stage IN ('draft','analysis','action','verification','closed','rejected')",
            name="ck_qms_ncr_stage",
        ),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    project_id = Column(UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False)
    code = Column(String(64), nullable=False)
    title = Column(String(256), nullable=False)
    source_alert_id = Column(UUID(as_uuid=True), nullable=True)
    scene_id = Column(UUID(as_uuid=True), nullable=True)
    station_id = Column(UUID(as_uuid=True), nullable=True)
    stage = Column(String(16), nullable=False, default="draft")
    verification_cycles = Column(Integer, nullable=False, default=0)
    reject_reason = Column(Text, nullable=True)
    closed_at = Column(DateTime, nullable=True)
    created_by_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_at = Column(DateTime, nullable=False, server_default=func.now())
    updated_at = Column(DateTime, nullable=False, server_default=func.now(), onupdate=func.now())


class QmsNcrAction(Base):
    __tablename__ = "qms_ncr_actions"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    ncr_id = Column(UUID(as_uuid=True), ForeignKey("qms_ncr_capas.id", ondelete="CASCADE"), nullable=False)
    phase = Column(String(16), nullable=False)
    action = Column(String(256), nullable=False)
    note = Column(Text, nullable=True)
    actor_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_at = Column(DateTime, nullable=False, server_default=func.now())

    __table_args__ = (Index("ix_qms_ncr_actions_ncr", "ncr_id", "created_at"),)


class QmsD8Report(Base):
    __tablename__ = "qms_d8_reports"
    __table_args__ = (
        UniqueConstraint("project_id", "code", name="uq_qms_d8_project_code"),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    project_id = Column(UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False)
    code = Column(String(64), nullable=False)
    title = Column(String(256), nullable=False)
    case_id = Column(UUID(as_uuid=True), nullable=True)
    ncr_id = Column(UUID(as_uuid=True), nullable=True)
    current_step = Column(Integer, nullable=False, default=0)
    steps = Column(JSON, nullable=False, default=dict)
    d6_passed = Column(Boolean, nullable=False, default=False)
    closed_at = Column(DateTime, nullable=True)
    created_by_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_at = Column(DateTime, nullable=False, server_default=func.now())
    updated_at = Column(DateTime, nullable=False, server_default=func.now(), onupdate=func.now())


class QmsCase(Base):
    __tablename__ = "qms_cases"
    __table_args__ = (
        UniqueConstraint("project_id", "code", name="uq_qms_cases_project_code"),
        CheckConstraint("severity IN ('low','medium','high','critical')", name="ck_qms_cases_severity"),
        CheckConstraint("status IN ('open','monitoring','closed')", name="ck_qms_cases_status"),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    project_id = Column(UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False)
    code = Column(String(64), nullable=False)
    title = Column(String(256), nullable=False)
    severity = Column(String(16), nullable=False, default="medium")
    status = Column(String(16), nullable=False, default="open")
    source_alert_id = Column(UUID(as_uuid=True), nullable=True)
    keywords = Column(String(256), nullable=True)
    created_by_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    closed_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, nullable=False, server_default=func.now())
    updated_at = Column(DateTime, nullable=False, server_default=func.now(), onupdate=func.now())


class QmsCaseLink(Base):
    __tablename__ = "qms_case_links"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    case_id = Column(UUID(as_uuid=True), ForeignKey("qms_cases.id", ondelete="CASCADE"), nullable=False)
    object_type = Column(String(32), nullable=False)
    object_id = Column(String(64), nullable=False)
    created_at = Column(DateTime, nullable=False, server_default=func.now())

    __table_args__ = (Index("ix_qms_case_links_case", "case_id"),)


class QmsKnowledgeEntry(Base):
    __tablename__ = "qms_knowledge_entries"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    project_id = Column(UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False)
    defect_code = Column(String(64), nullable=False)
    symptom = Column(Text, nullable=False)
    root_cause = Column(Text, nullable=True)
    action = Column(Text, nullable=True)
    effectiveness = Column(Text, nullable=True)
    device_ref = Column(String(128), nullable=True)
    created_by_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_at = Column(DateTime, nullable=False, server_default=func.now())
    updated_at = Column(DateTime, nullable=False, server_default=func.now(), onupdate=func.now())

    __table_args__ = (Index("ix_qms_knowledge_project", "project_id", "defect_code"),)


class QmsTraceLink(Base):
    __tablename__ = "qms_trace_links"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    project_id = Column(UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False)
    sample_key = Column(String(256), nullable=False)
    batch_no = Column(String(128), nullable=True)
    alert_id = Column(UUID(as_uuid=True), nullable=True)
    ncr_id = Column(UUID(as_uuid=True), nullable=True)
    inference_result_id = Column(UUID(as_uuid=True), nullable=True)
    dataset_version_id = Column(UUID(as_uuid=True), nullable=True)
    created_at = Column(DateTime, nullable=False, server_default=func.now())

    __table_args__ = (Index("ix_qms_trace_sample", "project_id", "sample_key"),)


class QmsQualityReport(Base):
    __tablename__ = "qms_quality_reports"
    __table_args__ = (
        UniqueConstraint("project_id", "period", "period_key", "generated_by",
                         name="uq_qms_reports_scope"),
        CheckConstraint("period IN ('daily','weekly','monthly')", name="ck_qms_reports_period"),
        CheckConstraint("generated_by IN ('scheduler','manual')", name="ck_qms_reports_generator"),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    project_id = Column(UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False)
    period = Column(String(16), nullable=False)
    period_key = Column(String(16), nullable=False)
    params = Column(JSON, nullable=False, default=dict)
    content = Column(JSON, nullable=False, default=dict)
    html = Column(Text, nullable=False, default="")
    generated_by = Column(String(16), nullable=False, default="manual")
    created_by_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_at = Column(DateTime, nullable=False, server_default=func.now())


class QmsControlPlan(Base):
    __tablename__ = "qms_control_plans"
    __table_args__ = (
        CheckConstraint("status IN ('active','archived')", name="ck_qms_plans_status"),
        Index("ix_qms_plans_project_status", "project_id", "status"),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    project_id = Column(UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False)
    code = Column(String(64), nullable=False)
    version = Column(Integer, nullable=False, default=1)
    status = Column(String(16), nullable=False, default="active")
    quality_points = Column(JSON, nullable=False, default=list)
    tightening_multiplier = Column(Float, nullable=False, default=1.0)
    decision_log = Column(JSON, nullable=False, default=list)
    effective_from = Column(DateTime, nullable=False, server_default=func.now())
    archived_at = Column(DateTime, nullable=True)
    created_by_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_at = Column(DateTime, nullable=False, server_default=func.now())


class QmsMsaStudy(Base):
    __tablename__ = "qms_msa_studies"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    project_id = Column(UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False)
    name = Column(String(128), nullable=False)
    part_count = Column(Integer, nullable=False)
    operator_count = Column(Integer, nullable=False)
    replicates = Column(Integer, nullable=False)
    data = Column(JSON, nullable=False, default=dict)
    grr_percent = Column(Float, nullable=True)
    ndc = Column(Integer, nullable=True)
    grade = Column(String(16), nullable=True)
    created_by_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_at = Column(DateTime, nullable=False, server_default=func.now())

    __table_args__ = (
        CheckConstraint(
            "grade IN ('acceptable','conditional','unacceptable') OR grade IS NULL",
            name="ck_qms_msa_grade",
        ),
    )


class QmsFmea(Base):
    __tablename__ = "qms_fmeas"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    project_id = Column(UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False)
    name = Column(String(128), nullable=False)
    items = Column(JSON, nullable=False, default=list)
    created_by_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_at = Column(DateTime, nullable=False, server_default=func.now())
    updated_at = Column(DateTime, nullable=False, server_default=func.now(), onupdate=func.now())


class QmsSupplier(Base):
    __tablename__ = "qms_suppliers"
    __table_args__ = (
        UniqueConstraint("project_id", "code", name="uq_qms_suppliers_project_code"),
        CheckConstraint("status IN ('active','disabled')", name="ck_qms_supplier_status"),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    project_id = Column(UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False)
    code = Column(String(64), nullable=False)
    name = Column(String(128), nullable=False)
    status = Column(String(16), nullable=False, default="active")
    created_by_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_at = Column(DateTime, nullable=False, server_default=func.now())


class QmsIqcRecord(Base):
    __tablename__ = "qms_iqc_records"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    project_id = Column(UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False)
    supplier_id = Column(UUID(as_uuid=True), ForeignKey("qms_suppliers.id", ondelete="RESTRICT"), nullable=False)
    arrival_count = Column(Integer, nullable=False)
    inspected_count = Column(Integer, nullable=False)
    defect_count = Column(Integer, nullable=False)
    scar_id = Column(UUID(as_uuid=True), nullable=True)
    created_by_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_at = Column(DateTime, nullable=False, server_default=func.now())


class QmsScar(Base):
    __tablename__ = "qms_scars"
    __table_args__ = (
        UniqueConstraint("iqc_record_id", name="uq_qms_scars_iqc_record"),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    project_id = Column(UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False)
    iqc_record_id = Column(UUID(as_uuid=True), ForeignKey("qms_iqc_records.id", ondelete="CASCADE"), nullable=False)
    cause = Column(Text, nullable=True)
    correction = Column(Text, nullable=True)
    verification = Column(Text, nullable=True)
    closed_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, nullable=False, server_default=func.now())
