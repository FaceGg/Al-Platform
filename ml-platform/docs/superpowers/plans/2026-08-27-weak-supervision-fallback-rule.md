# Weak Supervision Fallback Rule Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a removable weak-supervision fallback rule whose editable label applies only when no ordinary user rule matches.

**Architecture:** Extend the existing `AnnotationProcessRule` contract with an optional explicit `kind`, treating missing kinds as ordinary condition rules for compatibility. The React page owns default-rule creation and read-only fallback rendering; the quality service owns normalization, uniqueness validation, and condition-first fallback execution so API callers cannot bypass the semantics.

**Tech Stack:** React 18, TypeScript, Vitest, Testing Library, FastAPI, Pydantic, Python, pytest/unittest, SQLAlchemy.

---

## File Map

- Modify `ml-platform/frontend/src/api/spotWeldQuality.ts`: expose the shared `condition | fallback` rule kind in request types.
- Modify `ml-platform/frontend/src/pages/DataAnnotationPage.tsx`: create, render, validate, serialize, edit, and delete the fallback rule.
- Modify `ml-platform/frontend/src/pages/DataAnnotationPage.test.tsx`: cover default creation, non-duplication, read-only condition text, editing, deletion, serialization, and English copy.
- Modify `ml-platform/frontend/src/i18n/index.tsx`: add `Other` and `All other cases` localized strings.
- Modify `ml-platform/backend/app/services/spot_weld_quality.py`: normalize explicit rule kinds and execute the fallback only after condition rules miss.
- Modify `ml-platform/backend/tests/test_spot_weld_quality_service.py`: cover service validation and execution semantics.
- Modify `ml-platform/backend/tests/test_api_spot_weld_quality.py`: cover validate/create acceptance and normalized persistence.
- Modify `DEVELOPMENT_PLAN.md`: append implementation evidence, verification, risks, and remaining work without rewriting existing history.
- Modify `C:\Users\17723\.codex\DEVELOPMENT_EXPERIENCE.md`: append reusable API-contract experience after verification.

### Task 1: Frontend Rule Contract And Default Interaction

**Files:**
- Modify: `ml-platform/frontend/src/api/spotWeldQuality.ts:161-172`
- Modify: `ml-platform/frontend/src/pages/DataAnnotationPage.test.tsx`
- Modify: `ml-platform/frontend/src/pages/DataAnnotationPage.tsx:49-53, 167-176, 494-564, 1052-1101`
- Modify: `ml-platform/frontend/src/i18n/index.tsx`

- [ ] **Step 1: Write failing component tests for default fallback creation and rendering**

Add tests that navigate to automatic setup step 2, toggle weak supervision, complete the existing cluster-preview mock, and assert:

```typescript
expect(await screen.findByDisplayValue("其他")).toBeInTheDocument();
expect(screen.getByText("除以上规则之外")).toBeInTheDocument();
expect(screen.queryByLabelText(/fallback-rule 条件 1 类型/)).not.toBeInTheDocument();
```

Toggle weak supervision off and on again, then assert only one fallback label input exists. Switch the test i18n state to English and assert `Other` and `All other cases`.

- [ ] **Step 2: Run the new frontend tests and verify RED**

Run:

```powershell
cd ml-platform/frontend
npx vitest run src/pages/DataAnnotationPage.test.tsx
```

Expected: FAIL because no fallback rule or localized fallback copy exists.

- [ ] **Step 3: Extend the rule type and localized copy**

Change the API type to:

```typescript
export type AnnotationProcessRuleKind = "condition" | "fallback";

export interface AnnotationProcessRule {
  id: string;
  kind?: AnnotationProcessRuleKind;
  label: string;
  tokens: AnnotationProcessRuleToken[];
}
```

Add `fallbackLabel` and `fallbackCondition` to both `dataAnnotation` locale objects with Chinese values `其他`, `除以上规则之外` and English values `Other`, `All other cases`.

- [ ] **Step 4: Implement default creation and fallback-only rendering**

Give ordinary rules `kind: "condition"`. Add a helper that creates one fallback rule:

```typescript
const createFallbackRule = (label: string): AnnotationRule => ({
  id: `fallback-rule-${Date.now()}`,
  kind: "fallback",
  label,
  tokens: [],
});
```

In the weak-supervision checkbox handler, append this rule only on a `false -> true` transition and only when no current rule has `kind === "fallback"`. Do not recreate the rule immediately after deletion. In the rule body, branch on `rule.kind === "fallback"`: render the localized read-only condition copy and the normal editable label input, but omit token controls and add-condition action. Keep the existing top-right delete button enabled whenever another rule remains; a fallback rule must be deletable.

- [ ] **Step 5: Run the component tests and verify GREEN**

Run the same Vitest command. Expected: all `DataAnnotationPage` tests pass.

- [ ] **Step 6: Commit the frontend interaction slice**

```powershell
git add -- ml-platform/frontend/src/api/spotWeldQuality.ts ml-platform/frontend/src/pages/DataAnnotationPage.tsx ml-platform/frontend/src/pages/DataAnnotationPage.test.tsx ml-platform/frontend/src/i18n/index.tsx
git commit -m "feat: add weak supervision fallback rule UI"
```

### Task 2: Frontend Validation, Editing, Deletion, And Serialization

**Files:**
- Modify: `ml-platform/frontend/src/pages/DataAnnotationPage.test.tsx`
- Modify: `ml-platform/frontend/src/pages/DataAnnotationPage.tsx:524-564`

- [ ] **Step 1: Write failing tests for fallback label mutation and request payloads**

Add tests which:

1. Change the fallback label from `其他` to `未分类`.
2. Start automatic annotation and assert both validate and create payloads contain:

```typescript
expect.objectContaining({
  kind: "fallback",
  label: "未分类",
  tokens: [],
})
```

3. Delete the fallback rule and assert it is absent from both payloads while ordinary rules remain.
4. Set `label_dtype` to `int` and assert the default string fallback label blocks submission until edited to an integer-compatible value.

- [ ] **Step 2: Run the focused test and verify RED**

Run the DataAnnotationPage Vitest command. Expected: FAIL because serialization omits `kind` and fallback validation still requires condition tokens.

- [ ] **Step 3: Implement kind-aware serialization and validation**

Serialize every rule with `kind: rule.kind || "condition"`. Refactor label validation into one local helper used by both kinds. For fallback rules, require only a valid label and `tokens.length === 0`; for condition rules, retain the existing token validation. Keep at least one total rule as the existing weak-supervision minimum, but do not require a fallback rule after the user deletes it.

- [ ] **Step 4: Run focused tests and verify GREEN**

Run the DataAnnotationPage test file and expect all tests to pass.

- [ ] **Step 5: Commit frontend payload behavior**

```powershell
git add -- ml-platform/frontend/src/pages/DataAnnotationPage.tsx ml-platform/frontend/src/pages/DataAnnotationPage.test.tsx
git commit -m "test: cover fallback rule payload behavior"
```

### Task 3: Backend Normalization And Execution Semantics

**Files:**
- Modify: `ml-platform/backend/tests/test_spot_weld_quality_service.py:540-635`
- Modify: `ml-platform/backend/tests/test_api_spot_weld_quality.py`
- Modify: `ml-platform/backend/app/services/spot_weld_quality.py:226-257, 373-389`

- [ ] **Step 1: Write failing service tests**

Add tests proving:

```python
rules = normalize_annotation_process_rules(
    [
        {"id": "hot", "label": "hot", "tokens": condition_tokens},
        {"id": "other", "kind": "fallback", "label": "other", "tokens": []},
    ],
    columns=["temperature"],
    label_dtype="string",
)
self.assertEqual(rules[0]["kind"], "condition")
self.assertEqual(rules[1]["kind"], "fallback")
self.assertEqual(apply_annotation_process_rules({"temperature": 12}, rules)[0], "hot")
self.assertEqual(apply_annotation_process_rules({"temperature": 2}, rules)[0], "other")
```

Also assert `QUALITY_ANNOTATION_RULE_INVALID` for two fallback rules, an unknown kind, and fallback tokens that are not empty. Retain a test showing no fallback returns `(None, [])`.

Extend the existing generic automatic-annotation API test payload with one ordinary rule and one fallback rule. Assert validate returns success, create returns `201`, and the returned or database-loaded run persists explicit `condition` and `fallback` kinds.

- [ ] **Step 2: Run service tests and verify RED**

Run:

```powershell
cd ml-platform/backend
$env:PYTHONPATH=(Get-Location).Path
python -m pytest tests/test_spot_weld_quality_service.py -k "annotation_process_rules" -q
python -m pytest tests/test_api_spot_weld_quality.py -k "annotation and process_rules" -q
```

Expected: both focused paths FAIL because fallback rules are currently passed to the ordinary token validator.

- [ ] **Step 3: Implement normalization**

In `normalize_annotation_process_rules`:

```python
fallback_seen = False
kind = str(rule.get("kind") or "condition")
if kind not in {"condition", "fallback"}:
    raise QualityPipelineError("QUALITY_ANNOTATION_RULE_INVALID")
if kind == "fallback":
    if fallback_seen or raw_tokens:
        raise QualityPipelineError("QUALITY_ANNOTATION_RULE_INVALID")
    fallback_seen = True
    tokens = []
else:
    # existing token normalization and validation
```

Append normalized dictionaries containing `id`, explicit `kind`, `tokens`, and normalized `label`.

- [ ] **Step 4: Implement condition-first fallback execution**

Store the fallback rule while iterating. Evaluate only condition rules. Return the first condition match unchanged; after the loop, return the fallback label and a hit record whose reason is `未命中其他弱监督规则，使用兜底标签`. If no fallback exists, return `(None, [])`.

- [ ] **Step 5: Run service tests and verify GREEN**

Run both focused pytest commands from Step 2. Expected: all selected service and API tests pass, and persisted rules include explicit kinds.

- [ ] **Step 6: Commit backend semantics**

```powershell
git add -- ml-platform/backend/app/services/spot_weld_quality.py ml-platform/backend/tests/test_spot_weld_quality_service.py ml-platform/backend/tests/test_api_spot_weld_quality.py
git commit -m "feat: apply fallback labels after weak rules"
```

### Task 4: Documentation And Full Verification

**Files:**
- Modify: `DEVELOPMENT_PLAN.md`
- Modify: `C:\Users\17723\.codex\DEVELOPMENT_EXPERIENCE.md`

- [ ] **Step 1: Run focused frontend and backend suites**

```powershell
cd ml-platform/frontend
npx vitest run src/pages/DataAnnotationPage.test.tsx src/api/spotWeldQuality.test.ts

cd ..\backend
$env:PYTHONPATH=(Get-Location).Path
python -m pytest tests/test_spot_weld_quality_service.py tests/test_api_spot_weld_quality.py -q
```

Expected: zero failures.

- [ ] **Step 2: Run production and syntax verification**

```powershell
cd ml-platform/frontend
npm run build

cd ..\backend
python -m py_compile app/services/spot_weld_quality.py app/api/spot_weld_quality.py

cd ..\..
git diff --check
```

Expected: all commands exit `0`; only established non-failing build warnings may remain.

- [ ] **Step 3: Update project and shared experience records**

Append a new `DEVELOPMENT_PLAN.md` execution record with observed behavior, verified root cause, implementation, exact test counts, build result, risks, and remaining work. Append a reusable `EXP-AW-*` entry explaining that catch-all rule semantics require an explicit discriminated contract and server-side ordering rather than a client-only constant expression.

- [ ] **Step 4: Re-run documentation and repository checks**

```powershell
git diff --check
git status --short
git diff --stat
```

Expected: no whitespace errors; unrelated pre-existing worktree changes remain untouched and are reported separately.

- [ ] **Step 5: Commit only this feature's remaining files**

Stage explicit paths only, including the relevant `DEVELOPMENT_PLAN.md` append after reviewing concurrent edits. Do not stage unrelated CI, evidence, migration, or orchestration changes.

```powershell
git add -- DEVELOPMENT_PLAN.md ml-platform/frontend/src/api/spotWeldQuality.ts ml-platform/frontend/src/i18n/index.tsx ml-platform/frontend/src/pages/DataAnnotationPage.tsx ml-platform/frontend/src/pages/DataAnnotationPage.test.tsx ml-platform/backend/app/services/spot_weld_quality.py ml-platform/backend/tests/test_spot_weld_quality_service.py ml-platform/backend/tests/test_api_spot_weld_quality.py
git diff --cached --check
git commit -m "feat: add weak supervision fallback labels"
```

The shared experience file is outside the repository and must not be added to Git.
