# Image and Dependency Security Remediation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the vulnerable Python image baseline and dependency exception with a pinned, scanned, compatible production image set.

**Architecture:** Candidate images are pulled and scanned before any Dockerfile edit. The selected immutable image reference is recorded in a reviewed JSON evidence file and copied to all four production Python Dockerfiles. Python dependency changes remain in `requirements.txt`; the existing scanner and CI contracts become fail-closed without the cryptography exception.

**Tech Stack:** Docker/WSL, `aquasec/trivy:0.67.2`, Python 3.11, pip, pip-audit, MLflow, `unittest`, GitHub Actions, PowerShell 7.

---

## Task 1: Freeze Baseline and Add Security Contracts

**Files:**
- Create: `ml-platform/backend/tests/test_image_security_contracts.py`
- Create: `docs/security/python-base-image.json`
- Test: `ml-platform/backend/tests/test_week12_security_gates.py`

- [ ] **Step 1: Add RED contracts for image and dependency state.**

Create `test_image_security_contracts.py` with this complete contract:

```python
import json
import re
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
BACKEND = ROOT / "ml-platform" / "backend"
DOCKERFILES = tuple(BACKEND / name for name in (
    "Dockerfile",
    "Dockerfile.worker",
    "Dockerfile.inference",
    "Dockerfile.tensorboard",
))
BASE_RECORD = ROOT / "docs" / "security" / "python-base-image.json"
REQUIREMENTS = BACKEND / "requirements.txt"
EXCEPTION = ROOT / "docs" / "security" / "cryptography-pkcs7-mlflow-exception.json"


class ImageSecurityContractTests(unittest.TestCase):
    def test_all_production_python_images_use_one_immutable_reference(self):
        record = json.loads(BASE_RECORD.read_text(encoding="utf-8"))
        reference = record["reference"]
        self.assertRegex(reference, r"^[^@]+@sha256:[0-9a-f]{64}$")
        for path in DOCKERFILES:
            first_line = path.read_text(encoding="utf-8").splitlines()[0]
            self.assertEqual(first_line, f"FROM {reference}", path.name)

    def test_direct_security_dependencies_are_fixed(self):
        lines = {
            line.split("#", 1)[0].strip().casefold()
            for line in REQUIREMENTS.read_text(encoding="utf-8").splitlines()
            if line.split("#", 1)[0].strip()
        }
        self.assertIn("cryptography==50.0.*", lines)
        self.assertIn("jaraco.context==6.1.0", lines)
        self.assertIn("wheel==0.46.2", lines)

    def test_cryptography_exception_is_removed_after_clean_resolution(self):
        self.assertFalse(EXCEPTION.exists())


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run RED contracts.**

Run from `ml-platform/backend`:

```powershell
python -m unittest tests.test_image_security_contracts -v
```

Expected: failure because current `FROM` lines are `python:3.11-slim`, requirements contain `cryptography==49.0.*`, and the exception file exists.

- [ ] **Step 3: Capture baseline before any fix.**

Run in PowerShell 7:

```powershell
$Root = 'E:\codex_workspace\agent_spot_welding\.worktrees\week9-12-mlops-core'
git -C $Root rev-parse HEAD
git -C $Root status --short --branch
Get-FileHash "$Root\tmp\security-20260810\trivy-image-current.json" -Algorithm SHA256
```

Expected: current commit is recorded, user-owned `ModelLibraryPage.test.tsx` and temporary directories remain visible, and the existing scan file hash is preserved in the work log.

- [ ] **Step 4: Commit the RED contracts only.**

```powershell
git -C $Root add ml-platform/backend/tests/test_image_security_contracts.py
git -C $Root commit -m "test(security): freeze image remediation contracts"
```

Expected: one test-only commit; no user-owned file is staged.

## Task 2: Select and Record a Clean Base Image

**Files:**
- Modify: `docs/security/python-base-image.json`
- Test: `ml-platform/backend/tests/test_image_security_contracts.py`

- [ ] **Step 1: Pull supported Python 3.11 slim candidates in WSL.**

Use only candidates that preserve glibc and the existing scientific wheels. Start with the current Debian family and its supported previous stable family:

```powershell
wsl.exe -e bash -lc 'set -euo pipefail; for image in python:3.11-slim-bookworm python:3.11-slim-bullseye; do docker pull "$image"; done'
```

Expected: each pull either completes or produces a recorded external registry failure; no candidate is accepted from an incomplete pull.

- [ ] **Step 2: Scan each candidate with the same database and threshold.**

```powershell
wsl.exe -e bash -lc 'set -euo pipefail; mkdir -p /tmp/week12-base-scan; for image in python:3.11-slim-bookworm python:3.11-slim-bullseye; do tag=${image//:/-}; docker run --rm -v /var/run/docker.sock:/var/run/docker.sock -v trivy-cache:/root/.cache aquasec/trivy:0.67.2 image --skip-db-update --severity HIGH,CRITICAL --format json --output "/tmp/week12-base-scan/$tag.json" "$image"; done'
```

Expected: selected candidate report has zero HIGH and zero CRITICAL findings. Any nonzero candidate is rejected and its JSON remains evidence.

- [ ] **Step 3: Verify the selected digest and runtime architecture.**

```powershell
wsl.exe -e bash -lc 'set -euo pipefail; image=python:3.11-slim-bookworm; docker image inspect "$image" --format "{{index .RepoDigests 0}} {{.Architecture}}"'
```

Expected: output contains one `sha256:` digest and `amd64`, matching the project acceptance architecture. If Bookworm is not clean, repeat the same scan with the next supported candidate and record the chosen reference.

- [ ] **Step 4: Write the actual selected reference.**

Write `docs/security/python-base-image.json` from the verified Docker output with keys `schema_version`, `image`, `reference`, `architecture`, `scanner`, `scanner_database`, `scanned_at`, and `status`. `reference` must be the literal `repository@sha256:` followed by the 64-character lowercase hexadecimal digest returned by Docker; `status` must be `passed`.

- [ ] **Step 5: Run the contract and review the record.**

```powershell
python -m unittest tests.test_image_security_contracts.ImageSecurityContractTests.test_all_production_python_images_use_one_immutable_reference -v
Get-Content .\docs\security\python-base-image.json
```

Expected: the test remains RED until Dockerfiles are updated; the JSON contains no credentials, URLs with userinfo, or temporary paths.

## Task 3: Apply the Pinned Base to Every Production Python Image

**Files:**
- Modify: `ml-platform/backend/Dockerfile`
- Modify: `ml-platform/backend/Dockerfile.worker`
- Modify: `ml-platform/backend/Dockerfile.inference`
- Modify: `ml-platform/backend/Dockerfile.tensorboard`
- Modify: `ml-platform/backend/tests/test_image_security_contracts.py`

- [ ] **Step 1: Replace only the first `FROM` line in all four Dockerfiles.**

Copy the exact `reference` value from `docs/security/python-base-image.json` into each first line. Keep `WORKDIR`, package installation, non-root user, health checks, and commands unchanged.

- [ ] **Step 2: Run image contract tests.**

```powershell
python -m unittest tests.test_image_security_contracts.ImageSecurityContractTests.test_all_production_python_images_use_one_immutable_reference -v
```

Expected: PASS for all four Dockerfiles.

- [ ] **Step 3: Commit the base-image change.**

```powershell
git add docs/security/python-base-image.json ml-platform/backend/Dockerfile ml-platform/backend/Dockerfile.worker ml-platform/backend/Dockerfile.inference ml-platform/backend/Dockerfile.tensorboard
git commit -m "build(security): pin clean Python image base"
```

Expected: commit contains only the base record and four Dockerfile first-line changes.

## Task 4: Resolve Python Dependency Findings Without Exception

**Files:**
- Modify: `ml-platform/backend/requirements.txt`
- Delete: `docs/security/cryptography-pkcs7-mlflow-exception.json`
- Modify: `ml-platform/backend/tools/security_scans.py`
- Modify: `ml-platform/backend/tests/test_week12_security_gates.py`
- Modify: `ml-platform/backend/tests/test_ci_workflow.py`
- Modify: `.github/workflows/ci.yml`

- [ ] **Step 1: Add dependency-resolution RED tests.**

Extend `test_image_security_contracts.py` with a test that parses the generated `pip-audit.json` and asserts no vulnerability object remains for `cryptography`, `jaraco.context`, or `wheel`. Add a CI contract asserting the Week 12 scan command contains no `--pip-audit-exception` argument.

- [ ] **Step 2: Resolve the dependency set in a clean temporary environment.**

```powershell
$Root = 'E:\codex_workspace\agent_spot_welding\.worktrees\week9-12-mlops-core'
$Venv = Join-Path $Root 'temp_test\security-resolve-venv'
py -3.11 -m venv $Venv
& "$Venv\Scripts\python.exe" -m pip install --upgrade pip
& "$Venv\Scripts\python.exe" -m pip install --dry-run --report "$Root\temp_test\security-resolve.json" -r "$Root\ml-platform\backend\requirements.txt"
```

Expected: resolver reports a complete set. If MLflow 3.15 cannot resolve with cryptography 50, select the smallest compatible MLflow version shown by the resolver, update its pin, and repeat the command before touching application code.

- [ ] **Step 3: Update direct pins only after the resolver result is known.**

Set `cryptography` to the resolved 50.x fixed line. Add exact fixed versions for `jaraco.context` and `wheel` only when the clean report confirms compatibility. Keep all unrelated requirements unchanged. Do not use `pip install --force-reinstall` or a broad unbounded range.

- [ ] **Step 4: Run raw dependency audit with no exception.**

```powershell
& "$Venv\Scripts\python.exe" -m pip install "pip-audit==2.*"
& "$Venv\Scripts\pip-audit.exe" -r "$Root\ml-platform\backend\requirements.txt" --format json --output "$Root\temp_test\security-resolve-pip-audit.json"
```

Expected: exit code 0 and zero vulnerability entries. If nonzero, leave the failing JSON, fix the resolver input, and rerun; do not add an exception.

- [ ] **Step 5: Remove obsolete exception code and contracts.**

Delete the cryptography exception JSON and its CI argument. Keep generic exception parsing only where still used by React Router. Remove tests that assert the deleted exception and replace them with clean-report/fail-closed tests.

- [ ] **Step 6: Run focused tests and commit.**

```powershell
python -m unittest tests.test_image_security_contracts tests.test_week12_security_gates tests.test_ci_workflow -v
git diff --check
git add ml-platform/backend/requirements.txt ml-platform/backend/tools/security_scans.py ml-platform/backend/tests/test_image_security_contracts.py ml-platform/backend/tests/test_week12_security_gates.py ml-platform/backend/tests/test_ci_workflow.py .github/workflows/ci.yml docs/security/cryptography-pkcs7-mlflow-exception.json
git commit -m "fix(security): remove dependency vulnerability exception"
```

Expected: focused tests pass; staged deletion is limited to the obsolete exception file; no unrelated user file is staged.

## Task 5: Build and Scan the Complete Production Image Set

**Files:**
- Generate: `temp_test/security-20260810-final/`
- Modify: `ml-platform/backend/tests/test_image_security_contracts.py`

- [ ] **Step 1: Build backend, worker, inference, and TensorBoard images from the same commit.**

```powershell
wsl.exe -e bash -lc 'set -euo pipefail; cd /mnt/e/codex_workspace/agent_spot_welding/.worktrees/week9-12-mlops-core/ml-platform/backend; docker build --pull -t codex-week12-final-backend:latest -f Dockerfile .; docker build --pull -t codex-week12-final-worker:latest -f Dockerfile.worker .; docker build --pull -t codex-week12-final-inference:latest -f Dockerfile.inference .; docker build --pull -t codex-week12-final-tensorboard:latest -f Dockerfile.tensorboard .'
```

Expected: all four builds succeed from the pinned base digest and run as the existing non-root `app` user.

- [ ] **Step 2: Scan all four images and the application filesystem.**

```powershell
wsl.exe -e bash -lc 'set -euo pipefail; mkdir -p /mnt/e/codex_workspace/agent_spot_welding/.worktrees/week9-12-mlops-core/temp_test/security-20260810-final; for image in codex-week12-final-backend:latest codex-week12-final-worker:latest codex-week12-final-inference:latest codex-week12-final-tensorboard:latest; do name=${image%%:*}; docker run --rm -v /var/run/docker.sock:/var/run/docker.sock -v trivy-cache:/root/.cache aquasec/trivy:0.67.2 image --skip-db-update --severity HIGH,CRITICAL --exit-code 1 --format json --output "/mnt/e/codex_workspace/agent_spot_welding/.worktrees/week9-12-mlops-core/temp_test/security-20260810-final/$name.json" "$image"; done'
```

Expected: each image report has zero HIGH and zero CRITICAL. Also run the existing filesystem, Bandit, npm, and scoped Gitleaks commands through `tools.security_scans all`; aggregate status must be `passed`.

- [ ] **Step 3: Run full local regression after image/dependency changes.**

```powershell
python -m unittest tests.test_week12_security_gates tests.test_ci_workflow -v
python run_suite.py
```

Expected: security/CI contracts pass and the full backend module suite remains green.

- [ ] **Step 4: Commit scan evidence references and update the development record.**

Append one dated entry to `DEVELOPMENT_PLAN.md` and `C:\Users\17723\.codex\DEVELOPMENT_EXPERIENCE.md` with observed findings, root cause, selected digest, dependency versions, scan commands, verification, prevention, and any remaining external gate. Never copy tokens, URLs with credentials, private keys, or raw request data.

```powershell
git add DEVELOPMENT_PLAN.md docs/security/python-base-image.json
git commit -m "docs(security): record clean image verification"
```

Expected: record says `passed` only when all image reports are zero-finding; no exception expands.

## Security Plan Review

- Base image selection maps to Tasks 2-3 and contracts bind all four production Python images.
- Dependency remediation maps to Task 4 and removes the cryptography exception only after raw audit success.
- Final scanner state maps to Task 5 and preserves scoped React Router fail-closed behavior.
- No task uses an unknown version, broad suppression, skipped scanner, or mutable tag as final evidence.
- Dynamic values are obtained from explicit Docker/pip output, not invented in code or documentation.
