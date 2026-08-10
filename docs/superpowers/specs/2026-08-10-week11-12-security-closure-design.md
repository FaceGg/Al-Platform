# Week 11-12 Security and Acceptance Closure Design

## Status

Approved scope: close every remaining Week 11-12 security and release gate, not merely record exceptions. This design supersedes the temporary acceptance posture recorded on 2026-08-10 where the current backend image contained 26 HIGH/CRITICAL findings.

## Problem Statement

The current production backend image is built from `python:3.11-slim` on Debian 13.6. Trivy reports 26 HIGH/CRITICAL findings: 23 operating-system findings and three Python package findings. The direct Python dependency set pins `cryptography==49.0.*` while `mlflow==3.15.*` is present, so the existing PKCS#7 exception prevents a clean dependency result but does not remove the vulnerability.

Independent release evidence remains incomplete: a fixed 4 vCPU / 8 GiB performance baseline, real backup restore RTO/RPO evidence, a real N-1 database upgrade, complete external Chromium acceptance, a signed evidence manifest, and a successful remote GitHub Actions run.

## Goals

1. Produce production images with zero Trivy HIGH/CRITICAL findings, zero image secrets, and zero image misconfigurations.
2. Produce a dependency set with zero unapproved `pip-audit` findings. Remove the cryptography exception only after the resolver and runtime verification pass.
3. Keep all production Python images on one pinned, scanned base image policy.
4. Complete Week 11-12 acceptance evidence with real services and bounded resources.
5. Preserve user-owned uncommitted changes and runtime evidence. Do not weaken a failing scan, add broad ignore rules, or replace real evidence with synthetic success records.
6. Push verified work, obtain remote CI evidence, merge only after every required gate is green, and verify local and remote heads match.

## Non-Goals

- Rewriting runtime services around Alpine or distroless images without a demonstrated compatibility need.
- Treating a scanner exception, a stale image, a skipped test, or a local-only result as final acceptance.
- Removing `tmp/` evidence or user-owned files solely to make Git status clean.

## Candidate Base Image Strategy

Three approaches were considered.

1. Scan-first supported Debian slim replacement (selected): build a small, finite candidate set of Python 3.11 slim tags or digests, scan each with the same Trivy database and HIGH/CRITICAL threshold, then pin the first compatible zero-finding candidate. Rebuild all production Python images from that exact baseline.
2. Alpine/musl migration: potentially lowers Debian package exposure but risks unavailable or source-built scientific Python, ONNX Runtime, XGBoost, and MLflow dependencies. Rejected unless every supported Debian candidate fails.
3. Retain the current base and expand exceptions: rejected because it leaves the release gate failed and hides operating-system CVEs.

The selected base image must be immutable by digest. A regression test or static contract must verify that backend, worker, inference, and TensorBoard Python images use the same approved base policy. A base tag is not accepted until its built image, not only the upstream image metadata, scans cleanly.

## Dependency Remediation Design

1. Resolve dependencies in a clean environment before editing production pins.
2. Promote `cryptography` to a version that contains the CVE-2026-69247 fix, currently `50.0.0` or later within the verified constraint set.
3. Resolve and pin the scanned fixed versions of `jaraco.context` and `wheel`, without changing unrelated dependency families.
4. If MLflow 3.15 cannot resolve with the fixed cryptography version, identify the smallest compatible MLflow upgrade, run its API, worker, MinIO/S3, TensorBoard, and Compose regressions, and record the final exact versions.
5. Delete the cryptography compatibility exception and its CI wiring only after raw `pip-audit` is clean. Retain the React Router exception only under its existing fail-closed BrowserRouter-only proof.

No version is accepted solely because installation succeeds. Acceptance requires dependency resolution, `pip-audit`, backend tests, frontend tests, Docker build, and final Trivy image scans.

## Implementation Boundaries

- Update every production Python Dockerfile from one selected base policy; do not leave worker or inference images on the old base.
- Keep non-root users, cache mounts, health checks, image build contexts, and current runtime commands unchanged unless a compatibility failure proves a minimal change is required.
- Update `requirements.txt`, lock or constraint artifacts if introduced, security exception data, scanner tests, CI contracts, and documentation together.
- Add regression tests before implementation changes for shared base consistency and the absence of an active cryptography exception after remediation.
- Preserve existing React Router scanning behavior: any runtime RSC, SSR, server handler, dynamic load, namespace binding, or unmodelled alias must continue to fail closed.

## Acceptance Environment

All destructive or stateful acceptance runs use a unique Docker Compose project name, isolated ports, isolated PostgreSQL database, MinIO bucket, Redis namespace, and temporary evidence directory. Startup, validation, and teardown run in one WSL shell lifecycle. Teardown only targets the generated project resources.

The performance baseline requires a true 4 vCPU / 8 GiB WSL resource envelope. The approved procedure writes a scoped user-level `.wslconfig` with those limits, performs `wsl --shutdown`, verifies the effective Docker host capacity, runs three identical rounds, captures results, then restores the prior user configuration and shuts down WSL again. The original configuration is copied before modification and restored even when a validation round fails. This affects all local WSL sessions during the run.

## Closure Sequence

1. Record current branch, user modifications, current image digests, and baseline scan output.
2. Scan candidate base images and choose a verified zero-finding digest.
3. Create failing tests for shared base policy and clean dependency/exception behavior.
4. Apply minimal Dockerfile, dependency, scanner, CI, and documentation changes.
5. Build every production image and run Trivy filesystem and image scans. Require zero HIGH/CRITICAL, secrets, and misconfigurations.
6. Run backend suite, targeted security/CI tests, frontend tests, production build, and local Chromium tests.
7. In the controlled WSL envelope, run three performance rounds, real backup/restore, N-1 upgrade, full external Chromium acceptance, and evidence generation.
8. Validate evidence source constraints and generate final manifest and acceptance report.
9. Update `DEVELOPMENT_PLAN.md` and reusable experience with observed behavior, root cause, solution, verification, prevention, and remaining work.
10. Commit, push the branch, wait for required GitHub Actions jobs, address only evidence-backed failures, then merge to `main` after all jobs pass. Verify local `main`, remote `origin/main`, and the merged commit agree.

## Failure Policy

- A candidate base image with any HIGH/CRITICAL finding is rejected; no ignore entry is added.
- A dependency conflict is resolved by the smallest compatible supported dependency upgrade, followed by the full relevant test matrix. If no compatible clean set exists, record a blocked upstream dependency with reproducible resolver and scan evidence; do not claim closure.
- A WSL resource, Docker, network, registry, or GitHub outage is recorded with command output and retry evidence. It is an external blocker, not a passing result.
- Any test, scanner, or acceptance failure stops promotion and merge. Existing user files are neither deleted nor reverted to force a passing state.

## Success Criteria

- Final backend, worker, inference, and TensorBoard Python images use the approved pinned base policy and each scan with zero HIGH/CRITICAL findings.
- Raw `pip-audit`, official-registry `npm audit`, Bandit HIGH threshold, Trivy filesystem scan, and scoped Gitleaks scans pass without unreviewed suppressions.
- Backend, frontend, build, Chromium, WSL performance, backup restore, N-1 upgrade, web security, evidence manifest, and remote CI gates all pass with preserved artifacts.
- `DEVELOPMENT_PLAN.md`, `DEVELOPMENT_EXPERIENCE.md`, security evidence, Git history, remote branch, and `main` describe the same final state.
