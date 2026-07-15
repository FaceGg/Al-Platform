WEEK_TEST_MODULES: dict[int, list[str]] = {
    1: [
        "test_suite_manifest",
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
    ],
    2: [
        "test_dag",
        "test_engine_advanced",
        "test_engine_orchestrator",
        "test_run_reliability",
        "test_api_runs",
        "test_api_workflows",
        "test_workflow_versions",
    ],
    3: [
        "test_operator_contract",
        "test_operators_extended",
        "test_operators_mechanism",
        "test_artifact_service",
        "test_api_datasets",
        "test_training",
        "test_training_artifacts",
    ],
    4: [
        "test_weld_demo_service",
        "test_industrial_templates",
        "test_industrial_template_e2e",
    ],
}


ALL_TEST_MODULES = [
    module
    for week in sorted(WEEK_TEST_MODULES)
    for module in WEEK_TEST_MODULES[week]
]
