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
        "test_knowledge",
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
        "test_chat_api_publication",
        "test_model_port",
        "test_announcements_api",
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
        "test_agent_servitize",
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
        "test_agent_wiring_api",
        "test_agent_center_api",
        "test_agent_extras",
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
