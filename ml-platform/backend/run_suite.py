"""Run each test module individually with a clean database."""
import subprocess, sys, os, shutil, time

suite_dir = os.path.join(os.path.dirname(__file__), "tests")
backend_dir = os.path.dirname(__file__)

# Test files in dependency order (engine first, then API)
test_modules = [
    "test_weld_demo_service",
    "test_operator_contract",
    "test_industrial_templates",
    "test_dag",
    "test_engine_advanced",
    "test_engine_vector_store",
    "test_engine_orchestrator",
    "test_run_reliability",
    "test_operators_extended",
    "test_operators_mechanism",
    "test_app",
    "test_api_users",
    "test_api_projects",
    "test_api_workflows",
    "test_workflow_versions",
    "test_artifact_service",
    "test_api_datasets",
    "test_api_runs",
    "test_industrial_template_e2e",
    "test_api_chat",
    "test_api_compute",
    "test_api_monitor",
    "test_api_dashboard",
    "test_api_labeling",
    "test_api_platform",
    "test_api_algorithm",
    "test_api_model_library",
    "test_knowledge",
    "test_training",
    "test_training_artifacts",
    "test_agents",
]

project_dir = os.path.dirname(os.path.dirname(backend_dir))
DB_DIR = os.path.join(project_dir, "temp_test", "test-suite", str(int(time.time())))
os.makedirs(DB_DIR, exist_ok=True)

passed = 0
failed = 0
errors_list = []

for mod in test_modules:
    db_path = os.path.join(DB_DIR, f"test_{mod}.db")
    artifact_dir = os.path.join(DB_DIR, f"artifacts_{mod}")
    system_temp_dir = os.path.join(DB_DIR, f"system_{mod}")
    os.makedirs(system_temp_dir, exist_ok=True)
    env = os.environ.copy()
    env["DATABASE_URL"] = f"sqlite:///{db_path}"
    env["ARTIFACT_STORAGE_DIR"] = artifact_dir
    env["ML_PLATFORM_TEMP_DIR"] = os.path.join(DB_DIR, f"data_{mod}")
    env["TEMP"] = system_temp_dir
    env["TMP"] = system_temp_dir
    env["TMPDIR"] = system_temp_dir
    env["PYTHONPATH"] = backend_dir

    print(f"\n{'=' * 60}")
    print(f"  RUNNING: {mod}")
    print(f"  DB: {db_path}")
    print(f"{'=' * 60}")

    result = subprocess.run(
        [sys.executable, "-m", "unittest", f"tests.{mod}", "-v"],
        capture_output=True, text=True, cwd=backend_dir, env=env,
        timeout=120
    )

    # Print output (last 20 lines for brevity)
    lines = result.stdout.split("\n")
    for line in lines:
        if line.strip() and ("..." in line or "FAIL" in line or "ERROR" in line or "Ran " in line or "OK" in line or "FAILED" in line):
            print(f"  {line}")

    if result.returncode == 0:
        passed += 1
        print(f"  >>> {mod}: PASSED")
    else:
        failed += 1
        errors_list.append(mod)
        # Extract error details
        error_lines = []
        capture = False
        for line in lines:
            if "ERROR:" in line or "FAIL:" in line:
                capture = True
            if capture and line.strip():
                error_lines.append(line)
                if len(error_lines) > 30:
                    break
        print(f"  >>> {mod}: FAILED")
        if error_lines:
            print(f"  First errors:")
            for el in error_lines[:8]:
                print(f"    {el}")
        # Show stderr briefly
        if result.stderr.strip():
            stderr_short = "\n".join(result.stderr.strip().split("\n")[:5])
            print(f"  STDERR: {stderr_short}")

# Cleanup
shutil.rmtree(DB_DIR, ignore_errors=True)

print(f"\n{'=' * 60}")
print(f"  RESULTS: {passed} passed, {failed} failed out of {passed + failed} modules")
if errors_list:
    print(f"  Failed modules: {', '.join(errors_list)}")
print(f"{'=' * 60}")

sys.exit(0 if failed == 0 else 1)
