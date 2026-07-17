"""Run production-stack tests when explicitly enabled."""

import os
import subprocess
import sys


if os.getenv("RUN_PRODUCTION_INTEGRATION") != "1":
    print("RUN_PRODUCTION_INTEGRATION is not enabled; skipping production integration")
    raise SystemExit(0)

raise SystemExit(subprocess.call([
    sys.executable, "-m", "unittest", "tests.test_production_stack", "-v",
]))
