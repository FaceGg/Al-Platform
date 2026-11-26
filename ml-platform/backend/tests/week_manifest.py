WEEK_TEST_MODULES: dict[int, list[str]] = {
    1: [
        "test_suite_manifest",
        "test_genericization_contract",
        "test_module_imports",
        "test_app",
        "test_api_users",
        "test_api_projects",
        "test_api_dashboard",
        "test_api_platform",
        "test_api_algorithm",
        "test_api_model_library",
        "test_api_chat",
        "test_api_compute",
        "test_api_monitor",
        "test_api_labeling",
        "test_engine_vector_store",
        "test_vector_store_deserialization_guard",
        "test_knowledge",
        # 知识图谱五阶段流水线（2026-11-20 批次）：抽取/融合/投影/图查询
        "test_kg_pipeline",
        # 补齐路线第一批 F1（2026-11-25 起）：质量领域模型（B1-10）
        "test_quality_domain",
        # 字段角色排除挂钩（P1，D5）
        "test_automl_excluded_columns",
        # 推理结果明细（P2，B1-16）
        "test_inference_results",
        # 板块可见性与 quality 角色（P3，§7.1/D10）
        "test_role_visibility",
        # 外部数据源与 SQL 白名单（P4，B1-08/D7/D8）
        "test_external_data_sources",
        # 通知通道补齐：钉钉 + 短信网关（P5，B1-11/D9）
        "test_notification_channels_dingtalk_sms",
        # 第一批迁移合同 _105–_109（往返/旧数据保留/单一头/漂移门禁）
        "test_gap_batch1_migrations",
        # 补齐路线第一批 F2a（2026-11-26 起）：预警处置主干
        # 预警处置链路：确认防呆 / 流转图 / 快照不可变 / 误报回流 / 同因合并（B1-01/B1-02）
        "test_quality_alerts",
        # 三类来源接入：模型风险 / 参数超限 / 设备异常 + SLA 通知送达 + 演示并入
        "test_quality_alert_sources",
        # SPC 基线冻结与判据链（E08 前移）
        "test_quality_spc_baselines",
        # SOP 版本化与处置单快照取数口径（E07）
        "test_quality_sops",
        # 补齐路线第一批 F2b：闭环证据总览 12 环节 + 上线检查五项 + 证据链 ZIP 导出（B1-12/E21）
        "test_evidence_exports",
        # 补齐路线第一批 F3：监控驾驶聚合口径 + 驾驶舱/趋势/实时监控接口 + 推送流（B1-03/04/05）
        "test_quality_monitor",
        # 补齐路线第一批 F4：SPC 纯函数统计库（Nelson 1–8 / 控制图 / 能力指数，B1-06）
        "test_spc_statistics",
        # 补齐路线第一批 F5：接入开放——项目级只读 Key/宽限期轮换 + 三个只读资源 +
        # 接入契约幂等落库 + 页脚状态三态（B1-13/B1-07）
        "test_open_api",
        # 补齐路线第一批 F4：SPC 分析接口（两个来源、规格来源标注、判异登记预警，B1-06）
        "test_spc_api",
        # 补齐路线第一批 F4：漂移检测（特征直方图覆盖全部样本、基线、分级批检、接口，B1-09）
        "test_drift_detection",
        # 补齐路线第二批 S1（2026-11-26 起）：审批与审计底座
        # 迁移合同 _113（两审计表哈希链三列 + 链尾状态 + 动作审计 + 统一审批队列）
        "test_gap_batch2_migrations",
        # S1/R1 审计哈希链：两表成链、篡改/断链定位、三写入分支挂接、校验端点（B2-08/E10）
        "test_audit_hash_chain",
        # S1/R2 动作审计：七键脱敏、幂等去重、网关/chat 工具挂点、查询与 CSV（B2-08）
        "test_agent_action_audit",
        # S1/R3+R4 统一四眼审批中心：四眼/过期回收+提醒/指纹失效/水位线/执行器/投影（B2-07/B2-10）
        "test_approval_center",
        # S2a 划分与盲测地基（B2-G1）：三策略划分/指纹重放/轮次锁定/台账/E03 上限
        "test_dataset_splitting",
        "test_modeling_rounds",
        # S2b 发布治理链（B2-09/02/03/G2/G3）：门禁五项+不回退+Wilson+预授权四失效+回执
        "test_release_governance",
        # S3 标注质量链（B2-05/06/G4/E15）：九策略选样+κ仲裁+纯度门禁+伪标签凭证
        "test_label_quality",
        # S4 智能应用（B2-01/B2-04）：引用编号+问数注册表+七因子可信度+CBPE+模型卡指纹
        "test_audit_qa",
        # M2 五段全链贯通演练：预警→处置→标注→重训→灰度发布→回执（独立验收项）
        "test_gap_m2_drill",
        "test_agents",
        "test_api_annotations",
        "test_schemas_validation",
        "test_models_misc",
    ],
    2: [
        "test_dag",
        "test_engine_advanced",
        "test_engine_orchestrator",
        "test_run_reliability",
        "test_api_runs",
        "test_api_workflows",
        "test_workflow_versions",
        "test_workflow_execution_service",
        "test_websocket_manager",
        "test_api_workflows_direct",
    ],
    3: [
        "test_operator_contract",
        "test_operator_raw_outputs",
        "test_operators_extended",
        "test_evaluation_operator_execution",
        "test_model_artifact_sealing",
        "test_operators_mechanism",
        "test_artifact_service",
        "test_api_datasets",
        "test_dataset_import_contract",
        "test_data_version_migration_graph",
        "test_training",
        "test_training_artifacts",
        "test_operators_optimization",
        "test_operators_utility",
        "test_operators_visualization_execution",
        "test_all_operators",
        "test_python_script_runtime",
        "test_workflow_operator_regressions",
    ],
    4: [
        "test_weld_demo_service",
        "test_api_workflow_templates",
    ],
    5: [
        "test_config",
        "test_database_migrations",
        "test_database_production",
        "test_database_transfer",
        "test_storage",
        "test_artifact_storage_integration",
        "test_operator_artifacts",
        "test_artifact_migration",
        "test_task_dispatcher",
        "test_celery_workflows",
        "test_event_bridge",
        "test_readiness",
        "test_production_stack",
        "test_storage_factory",
        "test_events_local",
        "test_safe_expression",
        "test_outbound_security",
    ],
    6: [
        "test_experiment_config",
        "test_experiment_models",
        "test_experiment_tracking",
        "test_api_experiments",
        "test_iterative_training",
        "test_training_tasks",
        "test_training_recovery",
        "test_automl_tracking",
        "test_automl_catalog",
        "test_automl_search",
        "test_automl_ensemble",
        "test_automl_report",
        "test_tensorboard_gateway",
        "test_experiment_production_stack",
        "test_upload_paths",
    ],
    7: [
        "test_pipeline_scheduler",
        "test_api_schedules",
        "test_project_access",
        "test_api_project_access",
        "test_ci_workflow",
    ],
    8: [
        "test_model_registry_models",
        "test_onnx_conversion",
        "test_model_registry_service",
        "test_inference_runtime",
        "test_inference_deployment",
        "test_api_model_registry",
        "test_inference_production_stack",
        "test_inference_tasks",
    ],
    17: [
        "test_annotation_task_state",
        "test_annotation_task_state_api",
        "test_annotation_execution_statistics_migration",
        "test_annotation_strategies",
        "test_annotation_concurrency",
        "test_weighted_clustering_umap",
        "test_automl_multioutput",
        "test_automl_anomaly",
        "test_automl_anomaly_fleet_shared",  # 机群共享段（B2/B18/B20/B3，2026-11-14）
        "test_anomaly_drift",
        # 二期 M7/M5（2026-11-12）：工况分片路由挂载 + AE 第三族
        "test_condition_shard_routing",
        "test_anomaly_ae_preflight",
        "test_automl_anomaly_ae",
        # 三期 M8/M9/M10（2026-11-12）：机群设备级标定与迁移
        "test_fleet_device_calibration",
        # M6 机制先行（2026-11-13）：半监督档 1 标签阈值重标定（confirmed≥50 解锁）
        "test_anomaly_threshold_recalibration",
        "test_m6_precision_at_k",          # M6 判据② 验收证据（2026-11-13）
        # 2026-11-18 批次：无监督训练器缺席族跳过（193923b7 连续崩溃回归）
        "test_anomaly_trainer_unavailable",
        "test_label_schema",
        "test_label_schema_api",
        "test_run_suite",
        "test_spot_weld_quality_models",
        "test_spot_weld_features",
        "test_spot_weld_quality_service",
        "test_api_spot_weld_quality",
        "test_spot_weld_quality_tasks",
        "test_annotator_auth",
        "test_annotation_return_acceptance",
        "test_model_registration_contract",
        "test_acceptance_manifest",
        "test_async_operation_contract",
        "test_model_export_contract",
        "test_model_exports_api",
        "test_model_export_annotation_lineage",
        "test_api_workflow_publication",
        "test_offline_inference_contract",
        "test_portal_internal_api",
        "test_portal_admin_review",
        "test_saved_annotation_strategies_api",
        "test_security_contract",
        "test_waveform_samples",
        "test_demo_loop",
        "test_agent_loop_retrain",
        "test_chat_api_publication",
        "test_model_port",
        "test_model_port_envelope",
        "test_announcements_api",
        "test_spot_weld_quality_list_api",
        "test_s5_integration_criteria",
    ],
    9: [
        "test_inference_production_models",
        "test_inference_rollout",
        "test_inference_api_keys",
        "test_inference_rate_limit",
        "test_inference_observability",
        "test_model_cards",
        "test_api_inference_production",
    ],
    10: [
        "test_security_hardening",
        "test_platform_audit",
        "test_notification_models",
        "test_notification_outbox",
        "test_notification_channels",
        "test_api_notifications",
        "test_notification_production_stack",
    ],
    11: [
        "test_week11_12_tools",
        "test_week11_contracts",
    ],
    12: [
        "test_week12_security_gates",
        "test_auth_jwt_migration",
        "test_password_hashing",
        "test_evidence_manifest",
        "test_acceptance_environment",
        "test_image_security_contracts",
        "test_notification_receiver_acceptance",
    ],
    13: [
        "test_kubernetes_client",
        "test_kubernetes_cluster_api",
        "test_cloud_resource_migrations",
    ],
    14: [
        "test_kubernetes_executor",
        "test_kubernetes_job_api",
        "test_kubernetes_recovery",
        "test_kubernetes_logs",
    ],
    15: [
        "test_notebook_api",
        "test_image_catalog_api",
        "test_image_build_security",
        "test_gpu_scheduling",
    ],
    16: [
        "test_multi_cluster_scheduler",
        "test_resource_governance",
        "test_storage_mounts",
        "test_cluster_observability",
    ],
}


# AutoML Agent milestone suites (implementation plan 2026-10-22). Phases
# register their own test modules without occupying week keys; ``18`` stays
# reserved for the deferred Week 18 track.
PHASE_TEST_MODULES: dict[str, list[str]] = {
    "p1": [
        "test_suite_phase_manifest",
        "test_llm_profiles_api",
        "test_llm_gateway",
        "test_llm_provider_formats",
        # 2026-11-18 批次：流式并发运行时可调（动态门+PlatformOption）
        "test_llm_stream_concurrency",
        "test_usage_stats_daily",
        "test_agent_profile_data",
        "test_agent_contracts",
    ],
    "p2": [
        "test_agent_sandbox",
        "test_agent_runner",
        "test_agent_hard_gates",
        "test_agent_executor",
    ],
    "p3": [
        "test_agent_recipe",
        "test_agent_experience",
        "test_agent_serving_binding",
        "test_agent_recipe_gated_swap",
        # 2026-11-18 批次：agent_trace 思考沉淀 + 配方一键复用端点
        "test_agent_recipe_reuse",
        "test_agent_servitize",
        "test_closed_loop_ensemble",
    ],
    "p4": [
        "test_agent_skill_revision",
    ],
    "p5": [
        "test_agent_wizard",
        "test_agent_optimization_report",
    ],
    "p6": [
        "test_kb_bindings",
        "test_chat_tools",
        "test_chat_tool_orchestrator",
        "test_chat_stream2",
        "test_chat_sessions_pin",
        "test_agent_wiring_api",
        "test_agent_center_api",
        "test_agent_extras",
        "test_agent_cast_features",
        "test_agent_llm_retry",
        "test_agent_accuracy_alignment",
        "test_agent_cast_engine_reachable",
        "test_apply_model_feature_columns",
        "test_showcase_agent_template",
    ],
}


def _module_owner_groups() -> dict[str, list[str]]:
    """week + phase 合并视图：模块 → 拥有组列表（供 CI 无主校验与去重检查）。"""
    merged: dict[str, list[str]] = {}
    for week, modules in WEEK_TEST_MODULES.items():
        for module in modules:
            merged.setdefault(module, []).append(f"week:{week}")
    for phase, modules in PHASE_TEST_MODULES.items():
        for module in modules:
            merged.setdefault(module, []).append(f"phase:{phase}")
    return merged


MODULE_OWNERS = _module_owner_groups()


# Point-weld-quality modules are retained only as historical compatibility
# tests. They are not part of the generic platform acceptance contract.
# Run them explicitly with ``run_suite.py --include-deprecated --week 17``.
DEPRECATED_TEST_MODULES = {
    "test_spot_weld_quality_models",
    "test_spot_weld_features",
    "test_spot_weld_quality_service",
    "test_api_spot_weld_quality",
    "test_spot_weld_quality_tasks",
}


ALL_TEST_MODULES = [
    module
    for module in (
        [
            module
            for week in sorted(WEEK_TEST_MODULES)
            for module in WEEK_TEST_MODULES[week]
        ]
        + [
            module
            for phase in sorted(PHASE_TEST_MODULES)
            for module in PHASE_TEST_MODULES[phase]
        ]
    )
    if module not in DEPRECATED_TEST_MODULES
]
