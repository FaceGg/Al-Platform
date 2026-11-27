# -*- coding: utf-8 -*-
"""QMS compliance tables (补齐路线第三批, B3-01~B3-10, 技术方案 §1, 迁移 _118).

十四张新表一次建齐（T1/T2/T3 为验收分段非建表分段），全带 project_id 归属。
不动数据。SQLite batch；PG 原生。
"""
import sqlalchemy as sa
from alembic import op

revision = "20261126_118"
down_revision = "20261126_117"
branch_labels = None
depends_on = None

_TABLES = (
    "qms_ncr_capas", "qms_ncr_actions", "qms_d8_reports", "qms_cases",
    "qms_case_links", "qms_knowledge_entries", "qms_trace_links",
    "qms_quality_reports", "qms_control_plans", "qms_msa_studies",
    "qms_fmeas", "qms_suppliers", "qms_iqc_records", "qms_scars",
)


def _table_names() -> set:
    inspector = sa.inspect(op.get_bind())
    return set(inspector.get_table_names())


def upgrade() -> None:
    op.create_table(
        "qms_ncr_capas",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("project_id", sa.Uuid(),
                  sa.ForeignKey("projects.id", ondelete="CASCADE"), nullable=False),
        sa.Column("code", sa.String(length=64), nullable=False),
        sa.Column("title", sa.String(length=256), nullable=False),
        sa.Column("source_alert_id", sa.Uuid(), nullable=True),
        sa.Column("scene_id", sa.Uuid(), nullable=True),
        sa.Column("station_id", sa.Uuid(), nullable=True),
        sa.Column("stage", sa.String(length=16), nullable=False),
        sa.Column("verification_cycles", sa.Integer(), nullable=False),
        sa.Column("reject_reason", sa.Text(), nullable=True),
        sa.Column("closed_at", sa.DateTime(), nullable=True),
        sa.Column("created_by_id", sa.Uuid(),
                  sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("project_id", "code", name="uq_qms_ncr_project_code"),
        sa.CheckConstraint(
            "stage IN ('draft','analysis','action','verification','closed','rejected')",
            name="ck_qms_ncr_stage",
        ),
    )
    op.create_table(
        "qms_ncr_actions",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("ncr_id", sa.Uuid(),
                  sa.ForeignKey("qms_ncr_capas.id", ondelete="CASCADE"), nullable=False),
        sa.Column("phase", sa.String(length=16), nullable=False),
        sa.Column("action", sa.String(length=256), nullable=False),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("actor_id", sa.Uuid(),
                  sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_qms_ncr_actions_ncr", "qms_ncr_actions", ["ncr_id", "created_at"])
    op.create_table(
        "qms_d8_reports",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("project_id", sa.Uuid(),
                  sa.ForeignKey("projects.id", ondelete="CASCADE"), nullable=False),
        sa.Column("code", sa.String(length=64), nullable=False),
        sa.Column("title", sa.String(length=256), nullable=False),
        sa.Column("case_id", sa.Uuid(), nullable=True),
        sa.Column("ncr_id", sa.Uuid(), nullable=True),
        sa.Column("current_step", sa.Integer(), nullable=False),
        sa.Column("steps", sa.JSON(), nullable=False),
        sa.Column("d6_passed", sa.Boolean(), nullable=False),
        sa.Column("closed_at", sa.DateTime(), nullable=True),
        sa.Column("created_by_id", sa.Uuid(),
                  sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("project_id", "code", name="uq_qms_d8_project_code"),
    )
    op.create_table(
        "qms_cases",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("project_id", sa.Uuid(),
                  sa.ForeignKey("projects.id", ondelete="CASCADE"), nullable=False),
        sa.Column("code", sa.String(length=64), nullable=False),
        sa.Column("title", sa.String(length=256), nullable=False),
        sa.Column("severity", sa.String(length=16), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("source_alert_id", sa.Uuid(), nullable=True),
        sa.Column("keywords", sa.String(length=256), nullable=True),
        sa.Column("created_by_id", sa.Uuid(),
                  sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("closed_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("project_id", "code", name="uq_qms_cases_project_code"),
        sa.CheckConstraint("severity IN ('low','medium','high','critical')",
                           name="ck_qms_cases_severity"),
        sa.CheckConstraint("status IN ('open','monitoring','closed')",
                           name="ck_qms_cases_status"),
    )
    op.create_table(
        "qms_case_links",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("case_id", sa.Uuid(),
                  sa.ForeignKey("qms_cases.id", ondelete="CASCADE"), nullable=False),
        sa.Column("object_type", sa.String(length=32), nullable=False),
        sa.Column("object_id", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_qms_case_links_case", "qms_case_links", ["case_id"])
    op.create_table(
        "qms_knowledge_entries",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("project_id", sa.Uuid(),
                  sa.ForeignKey("projects.id", ondelete="CASCADE"), nullable=False),
        sa.Column("defect_code", sa.String(length=64), nullable=False),
        sa.Column("symptom", sa.Text(), nullable=False),
        sa.Column("root_cause", sa.Text(), nullable=True),
        sa.Column("action", sa.Text(), nullable=True),
        sa.Column("effectiveness", sa.Text(), nullable=True),
        sa.Column("device_ref", sa.String(length=128), nullable=True),
        sa.Column("created_by_id", sa.Uuid(),
                  sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_qms_knowledge_project", "qms_knowledge_entries",
                    ["project_id", "defect_code"])
    op.create_table(
        "qms_trace_links",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("project_id", sa.Uuid(),
                  sa.ForeignKey("projects.id", ondelete="CASCADE"), nullable=False),
        sa.Column("sample_key", sa.String(length=256), nullable=False),
        sa.Column("batch_no", sa.String(length=128), nullable=True),
        sa.Column("alert_id", sa.Uuid(), nullable=True),
        sa.Column("ncr_id", sa.Uuid(), nullable=True),
        sa.Column("inference_result_id", sa.Uuid(), nullable=True),
        sa.Column("dataset_version_id", sa.Uuid(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_qms_trace_sample", "qms_trace_links", ["project_id", "sample_key"])
    op.create_table(
        "qms_quality_reports",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("project_id", sa.Uuid(),
                  sa.ForeignKey("projects.id", ondelete="CASCADE"), nullable=False),
        sa.Column("period", sa.String(length=16), nullable=False),
        sa.Column("period_key", sa.String(length=16), nullable=False),
        sa.Column("params", sa.JSON(), nullable=False),
        sa.Column("content", sa.JSON(), nullable=False),
        sa.Column("html", sa.Text(), nullable=False),
        sa.Column("generated_by", sa.String(length=16), nullable=False),
        sa.Column("created_by_id", sa.Uuid(),
                  sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("project_id", "period", "period_key", "generated_by",
                            name="uq_qms_reports_scope"),
        sa.CheckConstraint("period IN ('daily','weekly','monthly')",
                           name="ck_qms_reports_period"),
        sa.CheckConstraint("generated_by IN ('scheduler','manual')",
                           name="ck_qms_reports_generator"),
    )
    op.create_table(
        "qms_control_plans",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("project_id", sa.Uuid(),
                  sa.ForeignKey("projects.id", ondelete="CASCADE"), nullable=False),
        sa.Column("code", sa.String(length=64), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("quality_points", sa.JSON(), nullable=False),
        sa.Column("tightening_multiplier", sa.Float(), nullable=False),
        sa.Column("decision_log", sa.JSON(), nullable=False),
        sa.Column("effective_from", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.Column("archived_at", sa.DateTime(), nullable=True),
        sa.Column("created_by_id", sa.Uuid(),
                  sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint("status IN ('active','archived')", name="ck_qms_plans_status"),
    )
    op.create_index("ix_qms_plans_project_status", "qms_control_plans",
                    ["project_id", "status"])
    op.create_table(
        "qms_msa_studies",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("project_id", sa.Uuid(),
                  sa.ForeignKey("projects.id", ondelete="CASCADE"), nullable=False),
        sa.Column("name", sa.String(length=128), nullable=False),
        sa.Column("part_count", sa.Integer(), nullable=False),
        sa.Column("operator_count", sa.Integer(), nullable=False),
        sa.Column("replicates", sa.Integer(), nullable=False),
        sa.Column("data", sa.JSON(), nullable=False),
        sa.Column("grr_percent", sa.Float(), nullable=True),
        sa.Column("ndc", sa.Integer(), nullable=True),
        sa.Column("grade", sa.String(length=16), nullable=True),
        sa.Column("created_by_id", sa.Uuid(),
                  sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint(
            "grade IN ('acceptable','conditional','unacceptable') OR grade IS NULL",
            name="ck_qms_msa_grade",
        ),
    )
    op.create_table(
        "qms_fmeas",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("project_id", sa.Uuid(),
                  sa.ForeignKey("projects.id", ondelete="CASCADE"), nullable=False),
        sa.Column("name", sa.String(length=128), nullable=False),
        sa.Column("items", sa.JSON(), nullable=False),
        sa.Column("created_by_id", sa.Uuid(),
                  sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
    )
    op.create_table(
        "qms_suppliers",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("project_id", sa.Uuid(),
                  sa.ForeignKey("projects.id", ondelete="CASCADE"), nullable=False),
        sa.Column("code", sa.String(length=64), nullable=False),
        sa.Column("name", sa.String(length=128), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("created_by_id", sa.Uuid(),
                  sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("project_id", "code", name="uq_qms_suppliers_project_code"),
        sa.CheckConstraint("status IN ('active','disabled')", name="ck_qms_supplier_status"),
    )
    op.create_table(
        "qms_iqc_records",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("project_id", sa.Uuid(),
                  sa.ForeignKey("projects.id", ondelete="CASCADE"), nullable=False),
        sa.Column("supplier_id", sa.Uuid(),
                  sa.ForeignKey("qms_suppliers.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("arrival_count", sa.Integer(), nullable=False),
        sa.Column("inspected_count", sa.Integer(), nullable=False),
        sa.Column("defect_count", sa.Integer(), nullable=False),
        sa.Column("scar_id", sa.Uuid(), nullable=True),
        sa.Column("created_by_id", sa.Uuid(),
                  sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
    )
    op.create_table(
        "qms_scars",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("project_id", sa.Uuid(),
                  sa.ForeignKey("projects.id", ondelete="CASCADE"), nullable=False),
        sa.Column("iqc_record_id", sa.Uuid(),
                  sa.ForeignKey("qms_iqc_records.id", ondelete="CASCADE"), nullable=False),
        sa.UniqueConstraint("iqc_record_id", name="uq_qms_scars_iqc_record"),
        sa.Column("cause", sa.Text(), nullable=True),
        sa.Column("correction", sa.Text(), nullable=True),
        sa.Column("verification", sa.Text(), nullable=True),
        sa.Column("closed_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
    )

    created = _table_names()
    for table in _TABLES:
        assert table in created, table


def downgrade() -> None:
    op.drop_table("qms_scars")
    op.drop_table("qms_iqc_records")
    op.drop_table("qms_suppliers")
    op.drop_table("qms_fmeas")
    op.drop_table("qms_msa_studies")
    op.drop_index("ix_qms_plans_project_status", table_name="qms_control_plans")
    op.drop_table("qms_control_plans")
    op.drop_table("qms_quality_reports")
    op.drop_index("ix_qms_trace_sample", table_name="qms_trace_links")
    op.drop_table("qms_trace_links")
    op.drop_index("ix_qms_knowledge_project", table_name="qms_knowledge_entries")
    op.drop_table("qms_knowledge_entries")
    op.drop_index("ix_qms_case_links_case", table_name="qms_case_links")
    op.drop_table("qms_case_links")
    op.drop_table("qms_cases")
    op.drop_table("qms_d8_reports")
    op.drop_index("ix_qms_ncr_actions_ncr", table_name="qms_ncr_actions")
    op.drop_table("qms_ncr_actions")
    op.drop_table("qms_ncr_capas")
