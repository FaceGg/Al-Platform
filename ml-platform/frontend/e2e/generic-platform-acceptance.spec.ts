import { expect, test } from "@playwright/test";

async function login(page: import("@playwright/test").Page) {
  await page.goto("/login");
  await page.getByPlaceholder("用户名").fill("admin");
  await page.getByPlaceholder("密码").fill("admin123");
  await page.locator('button[type="submit"]').click();
  await expect(page).toHaveURL(/\/$/);
}

test("accepts the generic annotation task workflow in the browser", async ({ page }) => {
  await login(page);

  let taskStatus = "awaiting_return";
  let previewStatus = "queued";
  const transitionActions: string[] = [];

  await page.route("**/api/projects", async (route) => {
    if (route.request().method() !== "GET") return route.fallback();
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({ items: [{ id: "project-1", name: "Generic project" }] }),
    });
  });
  await page.route("**/api/annotation-tasks**", async (route) => {
    const request = route.request();
    const url = new URL(request.url());
    if (request.method() === "GET" && url.pathname === "/api/annotation-tasks") {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          items: [{
            id: "task-1",
            project_id: "project-1",
            mode: "automatic",
            status: taskStatus,
            task_revision: transitionActions.length,
            sample_scope: { kind: "ids", sample_ids: ["sample-1"] },
            task_snapshot: { config_hash: "sha256:generic-task" },
          }],
          total: 1,
          next_cursor: null,
        }),
      });
      return;
    }
    if (request.method() === "POST" && url.pathname === "/api/annotation-tasks/task-1/preview") {
      previewStatus = "completed";
      await route.fulfill({
        status: 202,
        contentType: "application/json",
        body: JSON.stringify({
          operation_id: "operation-preview-1",
          preview_id: "preview-1",
          task_revision: 0,
          status: "queued",
        }),
      });
      return;
    }
    if (request.method() === "POST" && url.pathname === "/api/annotation-tasks/task-1/transition") {
      const payload = request.postDataJSON() as { action: string };
      transitionActions.push(payload.action);
      taskStatus = payload.action === "return"
        ? "returned_pending_acceptance"
        : payload.action === "accept"
          ? "accepted"
          : taskStatus;
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          id: "task-1",
          project_id: "project-1",
          mode: "automatic",
          status: taskStatus,
          task_revision: transitionActions.length,
        }),
      });
      return;
    }
    await route.fallback();
  });
  await page.route("**/api/annotation-tasks/task-1/previews/preview-1", async (route) => {
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        id: "preview-1",
        operation_id: "operation-preview-1",
        task_revision: 0,
        status: previewStatus,
        progress: previewStatus === "completed" ? 100 : 0,
        summary: { sample_count: 1 },
      }),
    });
  });
  await page.route("**/api/annotation-tasks/task-1/previews/preview-1/samples**", async (route) => {
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        items: [{ id: "preview-sample-1", sample_id: "sample-1", row_index: 0, values: { feature: 1 } }],
        total: 1,
        next_cursor: null,
      }),
    });
  });
  await page.route("**/api/annotation-operations**", async (route) => {
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({ items: [], total: 0, next_cursor: null }),
    });
  });

  await page.goto("/data-annotation?view=tasks&projectId=project-1");
  // 任务单元格渲染 <strong>task-1</strong> + <span>自动标注 · task-1</span>，须用精确匹配避免 strict mode 冲突
  await expect(page.getByText("task-1", { exact: true })).toBeVisible();
  await expect(page.getByText("点焊标注任务")).not.toBeVisible();
  await expect(page.getByText("SPOT WELD / TASKS")).not.toBeVisible();

  const list = page.getByRole("region", { name: "通用任务列表" });
  // awaiting_return 不在可指派状态列表（preview_ready/awaiting_annotation/in_progress）中
  await expect(list.getByRole("button", { name: "指派标注员" })).toBeDisabled();

  await list.getByRole("button", { name: "预览" }).click();
  const previewDrawer = page.getByRole("dialog", { name: "任务预览" });
  await expect(previewDrawer).toBeVisible();
  await expect(previewDrawer.getByText("sample-1")).toBeVisible();
  await previewDrawer.getByRole("button", { name: "关闭预览" }).click();
  await expect(previewDrawer).toBeHidden();

  await list.getByRole("button", { name: "提交回传" }).click();
  await expect.poll(() => transitionActions).toContain("return");
  await expect(list.getByRole("button", { name: "验收" })).toBeVisible();
  await list.getByRole("button", { name: "验收" }).click();
  await expect.poll(() => transitionActions).toContain("accept");
});

test("creates, configures, previews, and assigns a clustered automatic task", async ({ page }) => {
  await login(page);

  const taskName = "聚类发现任务";
  const outputContract = {
    model_version_id: "model-1",
    registered_model_id: "registered-model-1",
    model_name: "Quality classifier",
    version_number: 1,
    contract_hash: "sha256:quality-output",
    columns: [{ machine_key: "quality", display_name: "质量", value_type: "string", required: true }],
  };
  let taskCreated = false;
  let taskRevision = 0;
  let taskStatus = "draft";
  let savedConfigurationPayload: Record<string, unknown> | null = null;
  const creationPayloads: Record<string, unknown>[] = [];
  const assignmentPayloads: Record<string, unknown>[] = [];

  const snapshot = () => ({
    config_hash: taskRevision === 0 ? "sha256:cluster-discovery" : "sha256:cluster-final",
    visible_columns: ["temperature"],
    instructions: "Inspect quality",
    dataset_version: {
      id: "version-1",
      columns: [{ name: "temperature", dtype: "float64", nullable: false, position: 0 }],
    },
    label_schema: { columns: outputContract.columns },
    configuration: taskRevision === 0
      ? {
          clustering: true,
          cluster_discovery: true,
          model_version_id: "model-1",
          model_artifact_id: "artifact-1",
          model_output_contract: outputContract,
        }
      : {
          ...(savedConfigurationPayload?.configuration as Record<string, unknown> | undefined),
          model_version_id: "model-1",
          model_artifact_id: "artifact-1",
          model_output_contract: outputContract,
        },
  });

  const task = () => ({
    id: "task-clustered",
    project_id: "project-1",
    name: taskName,
    mode: "automatic",
    status: taskStatus,
    task_revision: taskRevision,
    sample_scope: { kind: "ids", sample_ids: ["sample-1", "sample-2", "sample-3"] },
    task_snapshot: snapshot(),
    preview: null,
  });

  await page.route("**/api/projects", async (route) => {
    if (route.request().method() !== "GET") return route.fallback();
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({ items: [{ id: "project-1", name: "Generic project", project_role: "owner" }] }),
    });
  });
  await page.route("**/api/datasets?project_id=project-1", async (route) => {
    if (route.request().method() !== "GET") return route.fallback();
    await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ items: [] }) });
  });
  await page.route("**/api/projects/project-1/dataset-versions", async (route) => {
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        items: [{
          id: "version-1",
          project_id: "project-1",
          source_name: "inspection.csv",
          version: 1,
          status: "ready",
          row_count: 3,
          column_count: 1,
          columns: [{ name: "temperature", dtype: "float64", nullable: false, position: 0 }],
        }],
      }),
    });
  });
  await page.route("**/api/projects/project-1/annotation-model-versions", async (route) => {
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        items: [{
          id: "model-1",
          registered_model_id: "registered-model-1",
          model_name: "Quality classifier",
          version_number: 1,
          algorithm: "random_forest",
          feature_schema: [{ name: "temperature", dtype: "float64" }],
          output_contract: outputContract,
        }],
      }),
    });
  });
  await page.route("**/api/annotation-tasks**", async (route) => {
    const request = route.request();
    const url = new URL(request.url());
    if (request.method() === "POST" && url.pathname === "/api/annotation-tasks") {
      creationPayloads.push(request.postDataJSON() as Record<string, unknown>);
      taskCreated = true;
      taskStatus = "draft";
      await route.fulfill({ status: 201, contentType: "application/json", body: JSON.stringify(task()) });
      return;
    }
    if (request.method() === "GET" && url.pathname === "/api/annotation-tasks") {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({ items: taskCreated ? [task()] : [], total: taskCreated ? 1 : 0, next_cursor: null }),
      });
      return;
    }
    if (request.method() === "PUT" && url.pathname === "/api/annotation-tasks/task-clustered/configuration") {
      savedConfigurationPayload = request.postDataJSON() as Record<string, unknown>;
      taskRevision = 1;
      taskStatus = "preview_ready";
      await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(task()) });
      return;
    }
    if (request.method() === "POST" && url.pathname === "/api/annotation-tasks/task-clustered/preview") {
      await route.fulfill({
        status: 202,
        contentType: "application/json",
        body: JSON.stringify({
          operation_id: taskRevision === 0 ? "operation-discovery" : "operation-final",
          preview_id: taskRevision === 0 ? "preview-discovery" : "preview-final",
          task_revision: taskRevision,
          status: "queued",
        }),
      });
      return;
    }
    if (request.method() === "GET" && url.pathname === "/api/annotation-tasks/task-clustered/assignments") {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({ items: [] }),
      });
      return;
    }
    if (request.method() === "POST" && url.pathname === "/api/annotation-tasks/task-clustered/assignments") {
      assignmentPayloads.push(request.postDataJSON() as Record<string, unknown>);
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          items: [{ id: "assignment-1", task_id: "task-clustered", annotator_subject_id: "annotator-1", state: "assigned" }],
          overlap_warning: null,
        }),
      });
      return;
    }
    await route.fallback();
  });
  await page.route("**/api/annotation-tasks/task-clustered/previews/preview-discovery", async (route) => {
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        id: "preview-discovery",
        operation_id: "operation-discovery",
        task_revision: 0,
        status: "completed",
        progress: 100,
        summary: { configuration_complete: false, needs_review_count: 0, clusters: [{ cluster_id: 0, sample_count: 3 }, { cluster_id: 1, sample_count: 1 }] },
      }),
    });
  });
  await page.route("**/api/annotation-tasks/task-clustered/previews/preview-final", async (route) => {
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        id: "preview-final",
        operation_id: "operation-final",
        task_revision: 1,
        status: "completed",
        progress: 100,
        summary: { configuration_complete: true, needs_review_count: 0, clusters: [{ cluster_id: 0, sample_count: 3 }, { cluster_id: 1, sample_count: 1 }] },
      }),
    });
  });
  await page.route("**/api/annotation-tasks/task-clustered/previews/**/samples**", async (route) => {
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        items: [
          { id: "preview-sample-1", sample_id: "sample-1", row_index: 0, values: { temperature: 10 } },
          { id: "preview-sample-2", sample_id: "sample-2", row_index: 1, values: { temperature: 11 } },
          { id: "preview-sample-3", sample_id: "sample-3", row_index: 2, values: { temperature: 12 } },
        ],
        total: 3,
        next_cursor: null,
      }),
    });
  });
  await page.route("**/api/annotations/label-schemas", async (route) => {
    if (route.request().method() !== "POST") return route.fallback();
    await route.fulfill({
      status: 201,
      contentType: "application/json",
      body: JSON.stringify({ id: "schema-1", project_id: "project-1", name: `${taskName}-labels`, version: 1 }),
    });
  });
  await page.route("**/api/annotations/saved-strategies**", async (route) => {
    if (route.request().method() !== "GET") return route.fallback();
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({ items: [] }),
    });
  });
  await page.route("**/api/annotators**", async (route) => {
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({ items: [{ id: "annotator-1", username: "inspector", display_name: "检查员", status: "active" }] }),
    });
  });
  await page.route("**/api/annotation-operations**", async (route) => {
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({ items: [], total: 0, next_cursor: null }),
    });
  });

  await page.goto("/data-annotation?view=tasks&projectId=project-1");
  await page.getByRole("button", { name: "新建自动标注任务" }).click();

  // 第 1 步：基本信息
  await page.getByLabel("任务名称").fill(taskName);
  await page.getByLabel("数据版本").selectOption("version-1");
  await page.getByLabel("已启用模型版本").selectOption("model-1");
  await page.getByRole("button", { name: "下一页" }).click();

  // 第 2 步：标注规则——弱监督 + 聚类发现
  await page.getByLabel("是否启用弱监督标注").selectOption("yes");
  await page.getByRole("button", { name: "生成聚类预览" }).first().click();

  await expect.poll(() => creationPayloads).toHaveLength(1);
  expect(creationPayloads[0]).toMatchObject({
    mode: "automatic",
    project_id: "project-1",
    dataset_version_id: "version-1",
    model_version_id: "model-1",
    name: taskName,
    configuration: { clustering: true, cluster_discovery: true },
  });

  // 聚类发现预览完成后，先保存标签 schema（策略编辑器解锁的前置条件）
  const schemaEditor = page.getByRole("region", { name: "标签 schema 编辑器" });
  await expect(schemaEditor).toBeVisible();
  await schemaEditor.getByLabel("枚举值 1 值 1").fill("ok");
  await schemaEditor.getByRole("button", { name: "保存 schema" }).click();

  const strategyEditor = page.locator('[aria-label="自动标注策略配置"]');
  await expect(strategyEditor).toBeVisible();
  await strategyEditor.getByLabel("自动标注策略").selectOption("cluster");
  await strategyEditor.getByRole("checkbox", { name: "簇 0 · 3 个样本" }).check();
  await strategyEditor.getByLabel("簇 0 质量").fill("clustered");
  await strategyEditor.getByLabel("其他兜底值 质量").fill("other");

  await page.getByRole("button", { name: "保存策略并完成" }).click();

  await expect.poll(() => (savedConfigurationPayload ? [savedConfigurationPayload] : [])).toHaveLength(1);
  expect(savedConfigurationPayload).toMatchObject({
    task_revision: 0,
    label_schema_id: "schema-1",
    configuration: {
      clustering: true,
      strategy: "cluster",
      selected_clusters: ["0"],
      cluster_labels: { "0": { "label-1": "clustered" } },
      other_values: { "label-1": "other" },
    },
  });

  // 最终预览完成后向导收尾，返回任务列表
  await expect(page.getByText("最终标签预览已完成，任务将自动开始执行。")).toBeVisible();
  await page.getByRole("button", { name: "返回任务列表" }).last().click();
  await expect(page.getByText(taskName, { exact: true })).toBeVisible();

  const list = page.getByRole("region", { name: "通用任务列表" });
  await expect(list.getByRole("button", { name: "指派标注员" })).toBeEnabled();
  await list.getByRole("button", { name: "指派标注员" }).click();

  const assignmentDialog = page.getByRole("dialog", { name: "指派任务" });
  await expect(assignmentDialog).toBeVisible();
  await assignmentDialog.locator(".ant-select-selector").click();
  await page.getByTitle("检查员").click();
  await assignmentDialog.getByRole("button", { name: "确认指派" }).click();
  await expect.poll(() => assignmentPayloads).toHaveLength(1);
  expect(assignmentPayloads).toEqual([{
    annotator_ids: ["annotator-1"],
    sample_scope: { kind: "ids", sample_ids: ["sample-1", "sample-2", "sample-3"] },
  }]);
});
