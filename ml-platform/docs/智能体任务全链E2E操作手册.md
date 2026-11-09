# 智能体任务全链 E2E 操作手册（点焊实例 · API + 大屏 + 本地 Python 验证）

> 适用版本：2026-11-09 之后（commit faa57379 含五项缺陷修复 + agent 模板大屏准入）。
> 与《智能体任务一键部署操作指南》（纯页面向导）互补：本手册记录一条**可复现的全链操作路径**——从新建智能体任务到部署 API/闭环自动化/应用编排三件套，再到大屏验证与本地 Python 调 API 验证，每一步给出真实请求与实测结果。
> 实例链路证据链：run `af96f7c6` → 配方 `7d90306f` v1 → 铸造 job `fbe7ec1e` → 部署 `b7f06a6b`（running）→ 闭环 loop `f8b0d721` → 编排 API v4 `87e5c0c6`（版本端点 `f92de32d`）。

---

## 0. 前置条件

| 项 | 要求 | 本例现状 |
|---|---|---|
| 平台服务 | `docker compose up -d` 全栈运行，`http://localhost` 可访问 | backend/frontend/nginx/postgres/worker/inference-runtime |
| 账号 | admin（或项目成员账号） | admin / admin123 |
| 数据集 | 项目内已上传训练数据 | 点焊项目 `train_v2__full.csv`（2180 行 × 91 列，目标列 `fault`），artifact id `28a82512-8b66-490f-b306-1b42bce9c9fd` |
| 大模型档案 | 至少一个已配 Key 的档案（S4 评审用） | DeepSeek 档案 `9c49153c-...`，连通 OK |
| 测试数据 | 本地测试 CSV | `C:\Users\17723\Desktop\点焊数据\train_v2_test.csv`（5000 行） |
| Python | 本机任意 Python 3.8+（验证脚本纯标准库，无需 pandas） | miniconda |

> **注意**：登录接口限流 15 分钟 5 次/IP。脚本批量操作务必复用 token（登录一次保存到文件）。
>
> ```bash
> curl -s -X POST http://localhost/api/auth/login -d 'username=admin&password=admin123'
> # 响应中的 access_token 存文件复用，后续请求带 Authorization: Bearer <token>
> ```

---

## 1. 新建智能体任务（AutoML 建模）

**POST** `/api/agent/runs`，请求体要点（完整模板见下）：

```json
{
  "project_id": "<项目id>",
  "dataset_artifact_id": "<数据集 artifact id>",
  "target_column": "fault",
  "model_profile_id": "<大模型档案id>",
  "guidance": {
    "suggest_drop": ["organization_code", "organization_name", "area_code",
                     "area_name", "wldindex", "cvepath"],
    "must_keep": ["wld1c", "wld1t", "wld2c", "wld2t", "tipv1", "capv1",
                  "ron1", "tipv2", "capv2", "ron2", "wres", "energy", "pulse"],
    "metric_gates": {"recall_minority": 0.9, "f1": 0.8},
    "review_focus": "防捷径特征；报告次要类召回与整体 f1",
    "auto_servitize": false
  }
}
```

**四个关键坑**（本例实测踩过）：

1. `dataset_artifact_id` 必须用**数据集列表项的 id**（artifacts 表 id），不是 dataset_versions id——用错报 `ArtifactAccessError`。
2. `auto_servitize` 必须放在 **guidance 内部**，放顶层无效。
3. `guidance.suggest_drop` 要列出组标识泄漏列（组织编码/区域名/wldindex 等），否则指标虚高、S4 评审否决。
4. S1 契约校验偶发严格（如 `leakage_suspects[].why` 缺失）——失败重提一次即可，属偶发。

**启动后轮询**：`GET /api/agent/runs/{run_id}`，观察 stage 流转
`S1 数据分析 → S2 特征工程（沙箱）→ S3 全量训练 → S4 硬门禁+LLM 评审 → accepted`。

**评审升级处理**：S4 可能 `waiting_escalate`（评审保守意见/指标门禁质疑）。查看 run 档案的 review/hints：
- 泄漏特征被正确拦截（如满分指标列）→ 该驳回是对的，按 hints 调整 guidance 重提；
- 指标真实达标（本例 recall_minority 0.986 / precision 0.921 / f1 0.952，硬门禁全过）仅评审保守 → **人工采纳**：
  `POST /api/agent/runs/{run_id}/decision` `{"action": "accept", ...}`。

---

## 2. 一键部署三件套（API → 闭环自动化 → 应用编排）

### 2.1 固化配方

```bash
POST /api/agent/recipes/fixate   {"run_id": "<run_id>"}
# → recipe id（本例 7d90306f，v1，含特征脚本/门禁/白名单/重放快照）
```

### 2.2 铸造部署（mode=engine）

```bash
POST /api/agent/servitize/cast-deployment
{"recipe_id": "...", "project_id": "...", "run_id": "...",
 "dataset_artifact_id": "...", "mode": "engine", "max_trials": 8}
# → 返回 job id（fbe7ec1e），轮询：
GET /api/agent/servitize/cast-deployment/{job_id}?recipe_id=...
# → deployment running（本例 b7f06a6b，模型版本 66bcce68，36 特征=13 原始+23 派生）
```

> 铸造耗时秒级～分钟级（引擎重训 8 trials 上限）。部署就绪后可在页面「服务化操作流」看到 ② 已完成。

### 2.3 服务化（生成闭环 + 模型 API 草稿）

```bash
POST /api/agent/servitize
{"recipe_id": "...", "deployment_id": "...", "model_api_name": "智能体闭环-<配方id>"}
# → 闭环 loop id（f8b0d721）+ 模型 API id（96a0dbf5），冒烟 prediction "1" 零回流
```

### 2.4 闭环绑定智能体重训

```bash
PUT /api/projects/{pid}/demo-loop/loops/{loop_id}
{"retrain_mode": "agent", "retrain_agent_recipe_id": "<recipe_id>", "retrain_enabled": true}
```

### 2.5 一键发布（API + 编排同时上架）

```bash
POST /api/agent/servitize/publish
{"model_api_id": "...", "project_id": "..."}
# → 模型 API published + 编排 API（六算子模板实例化并发布）
```

> **时序坑**：首次 publish 时闭环尚未产生回流，报错数据集未创建，会报
> `422 ORCHESTRATION_ERROR_DATASET_MISSING`——这是**预期的 fail-closed 保护**（修复后行为）。
> 先让闭环产生一条真实回流（见 §4 本地 Python 调 predict，fault=1 的行会触发 error_matched 回流），
> 报错数据集惰性创建后重新发布即可。

发布完成后：
- **API 市场**出现「智能体闭环」模型 API 条目（published）；
- **应用编排**出现六算子工作流（api_input → python_script(S2 特征) → load_deployment_model → apply_model → append_error_dataset → agent_retrain_threshold），并生成编排 API。

---

## 3. 大屏验证（闭环自动化 + 应用编排）

大屏地址：`http://localhost/demo-showcase.html`。

### 3.1 连接数据源

1. 打开大屏 → 点「模式：实时」展开连接面板；
2. Token 框粘贴登录 token（或先在主界面登录自动读取）；
3. 数据源二选一：
   - **闭环任务**：选项目 → 选闭环任务 → 连接 → 轮询 `/api/projects/{pid}/demo-loop/loops/{id}/status`；
   - **编排 API**：选项目 → 选编排 API（列表只显示**具备大屏资格**的条目）→ 连接 → 轮询 `/api/platform/apis/orchestration/{version_id}/showcase-status`。

### 3.2 验证要点（本例实测）

| 检查项 | 预期 | 本例结果 |
|---|---|---|
| 连接指示灯 | 常绿 | ✓ |
| 已推理计数 | 随外部 invoke 实时递增 | 23→27（外部 4 次 invoke 全部反映）|
| 阈值监测 | 显示 重训阈值 0/12 | ✓（读自 agent_retrain_threshold 节点）|
| 重训模式 | 「智能体」 | ✓（agent 模板自动感知）|
| console / toast | 无错误、无 409 SHOWCASE_NOT_ELIGIBLE | ✓ |

**驱动动画**：向编排 API 连续 invoke 原始行（见 §4.3 的 invoke 脚本），大屏计数秒级递增，故障行触发「报错回流→告警→智能体重构」粒子动画。

> **资格说明**：编排 API 需由服务化发布的三算子/六算子模板**原样创建**才上大屏（引擎七算子模板与 agent 六算子模板双白名单）；在画布上增删过算子的 API 会报 409 不支持大屏。

---

## 4. 本地 Python 验证（解析 CSV → 调预测 API）

脚本：`temp_test/sw_api_test.py`（纯标准库，无需安装依赖）。

### 4.1 为什么不能直接送原始行

部署 predict 端点（ONNX runtime）要求**恰好 36 个特征键、全数值**：
- 13 原始列（wld1c/wld2c/.../spotposition）；
- 23 派生列（c1_ratio/dt_prev_log/energy_ma50/...）——由配方 S2 特征脚本生成，**部署端点不执行该脚本**，需本地按同样语义计算。

脚本已实现（批量路径按 weld_time 排序计算滚动/序列特征后还原行序；行数不足用可用前缀兜底；缺值按单行服务路径语义回填 ratio→1.0、差值/相位→0.0）。

**spotposition 编码**：训练帧经 `astype("category").cat.codes` 编码为 int64（唯一值字典序 `{2:0, 3:1, 4:2, 5:3}`，未见类别 -1）——脚本已内置映射。

### 4.2 运行

```bash
python temp_test/sw_api_test.py                # 默认 200 行
python temp_test/sw_api_test.py --limit 0      # 全量 5000 行
python temp_test/sw_api_test.py --verbose      # 打印前 10 行预测明细
```

脚本自动完成：登录 → 找项目 → 找 running 部署 → 解析 CSV → 本地派生特征 → 分批（≤100 行/批）POST `/api/inference-deployments/{dep_id}/predict` → 分布统计 → 与 fault 列比对准确率（≥0.5 断言）。

**本例实测**：5000/5000 成功，分布 `{0: 4483, 1: 517}`，准确率 **90.26%**（200 行子集 100%）。

### 4.3 向编排 API 造数（驱动大屏/回流）

编排图内含 S2 变换，**送原始行即可**（无需本地算派生特征）：

```python
POST /api/platform/apis/orchestration/{version_id}/invoke
{"record": { ...原始 CSV 行去掉 fault 列... }}
```

- fault=1 的行预测为 1 → `error_matched` → 报错回流（error_count 累积）；
- 累积达阈值（本例 12 行）→ `agent_retrain_threshold` 状态机触发配方重放（护栏：单飞/冷却/24h 熔断 3 次）。

---

## 5. 常见问题与运维坑（本例实测）

| 现象 | 根因与处理 |
|---|---|
| 登录 403 | 15min 5 次/IP 限流——复用 token 文件，勿反复登录 |
| predict 409 `INFERENCE_SCHEMA_MISMATCH` | 记录键集与模型 feature_schema 不完全一致（多送/少送/字符串列未编码）。本例：t1_ratio 训练帧常量被 S2 剔除不送；spotposition 必须 cat.codes 数值 |
| 编排 invoke 409 权限拒绝 | `/tmp/ml-platform` 被 root 属主占用（容器内 root 跑过 pytest）：`docker exec -u root <backend> chown -R 1000:1000 /tmp/ml-platform` |
| 容器内 pytest 大面积假阳性失败 | 容器 env 的 DATABASE_URL 指向共享 dev 库——须 `-e DATABASE_URL= -e APP_MODE=local` 密封 sqlite（conftest 兜底才会生效） |
| 首次 publish 422 `ORCHESTRATION_ERROR_DATASET_MISSING` | 预期保护：先产生闭环回流（predict 一条 fault=1 行）再发布 |
| v4 invoke 200 但响应无 prediction 行 | 编排拓扑末节点是重训节点，预测结果在事件留痕（showcase-status 轮询读取），不影响大屏 |
| showcase 409 `SHOWCASE_NOT_ELIGIBLE` | 编排 API 在画布上增删过算子，不符合模板原样结构——重新由服务化发布 |

---

## 6. 关键资产速查（本例）

| 资产 | ID |
|---|---|
| 项目「点焊」 | `ba42e8d5-51c6-49a9-abef-af6019491fc8` |
| 数据集 artifact | `28a82512-8b66-490f-b306-1b42bce9c9fd` |
| 智能体 run（accepted） | `af96f7c6-e1ca-48da-b4f7-1ea411ecc251` |
| 配方 v1 | `7d90306f-583a-4d27-9a1e-731a0dd2098f` |
| 部署（running） | `b7f06a6b-c9b2-4f69-ac26-6d53bb364079`（模型版本 66bcce68） |
| 闭环 loop | `f8b0d721-8d6d-47d5-a6d6-1c5be5f8b731`（模型 API 96a0dbf5） |
| 报错回流数据集 | `b6889b93-489c-470b-8a5d-894dbb93326a` |
| 编排工作流 | `21b838ad-f0ca-42d5-9c8d-4d7a00bdcefa`（v4 版本 f92de32d，API 87e5c0c6） |
| 本地测试脚本 | `temp_test/sw_api_test.py` |
