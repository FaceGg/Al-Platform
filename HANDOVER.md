# 标注平台交接文档

> 更新时间：2026-09-21 ｜ 工作树：`general-automl-annotation-20260902`

## 1. 项目概况

通用 AutoML 与数据标注平台（代号 Linkraft），三条产品线 + 一个网关：

| 模块 | 技术栈 | 访问地址 |
|---|---|---|
| 主平台（管理端） | `ml-platform/frontend`，React + Antd + Koa | http://127.0.0.1:5173 |
| 标注员门户 | `ml-platform/annotator/frontend`，React + Vite + 自定义 CSS（无 Antd） | http://localhost:8443 |
| 门户网关 | `ml-platform/annotator/backend`，FastAPI + httpx（独立 app） | host 8444 → 容器 8443 |
| 主后端 | `ml-platform/backend`，FastAPI + SQLite（本地 `ml_platform.db`） | http://localhost:8000 |

**三层链路（重要）**：门户前端调 `/portal/*` → 网关（8444）校验 `portal_session` cookie（经主后端 `/portal/auth/me` 解析身份）→ 网关铸造 60s service token（JWT，携带 `annotator_subject_id` 或 `admin_user_id` claim）→ 主后端 `/api/internal/portal/*`（scope 校验 + subject/admin 归属校验）。管理员身份走无状态 JWT 门户会话（不写 `AnnotatorSession` 表，零 schema 变更）。

## 2. 部署与网络链路（本地开发环境）

```
浏览器
 ├─ 8443  → Docker nginx（annotator-frontend 容器）
 │            └→ annotator backend（网关）容器 :8443
 │                 └→ host.docker.internal:8100（WSL TCP 中继，wsl_relay.py）
 │                      └→ Windows uvicorn 0.0.0.0:8000（SQLite ml_platform.db）
 └─ 5173  → 主平台前端（Vite dev server）
```

### 常用命令与测试基线（2026-09-21）

```powershell
# 标注员门户前端（ml-platform/annotator/frontend）——基线 94 passed（13 文件）
npx vitest run; npx tsc --noEmit; npm run build

# 主平台前端（ml-platform/frontend）——基线 347 passed / 19 skipped（63+ 文件）
npm test; npx tsc --noEmit; npm run build

# 主后端（ml-platform/backend，venv .\.venv）——过滤套件基线 226 passed / 5 skipped
.\.venv\Scripts\python.exe -m pytest tests -q -k "portal or return or comment or annotator"
# 回传验收/导出专项：tests/test_annotation_return_acceptance.py —— 基线 18 passed
.\.venv\Scripts\python.exe -m pytest tests/test_annotation_return_acceptance.py -q
# 网关（ml-platform/annotator/backend，共用主 venv 绝对路径）——基线 27 passed
e:\<worktree>\ml-platform\backend\.venv\Scripts\python.exe -m pytest tests -q

# 部署标注员门户到 8443
wsl sh -c "cd /mnt/e/codex_workspace/agent_spot_welding/.worktrees/general-automl-annotation-20260902 && docker compose build annotator-frontend -q && docker compose up -d annotator-frontend"
curl.exe -s http://localhost:8443/ | Select-String "index-"   # 确认新 bundle hash
```

主后端全量套件（20260921_60 链头下）：**1986 passed / 1 failed**（notification 降级断言，修复后单文件 8 passed 转绿）。既有环境失败已从 18 个收敛（Alembic 迁移头/发布证据常量已随 20260921_60 同步、Dockerfile 断言已归一化）；仍存 pyarrow 缺失致 parquet 相关 7 例（本机 venv 环境问题）。新测试模块必须登记 `tests/week_manifest.py`（`test_suite_manifest` 强制约束）。全量套件未在 20260921_60 链头下完整重跑（并行会话编辑冲突风险），60 号迁移相关 head 账目测试已针对性复跑通过。

### 电脑重启后的恢复清单（重要，2026-09-21 实操验证）

**一键恢复**：右键"使用 PowerShell 运行" `temp_test/start_portal.ps1`（依次完成下列全部步骤并自动验证）。手动分步执行如下：

1. 清理 8000 端口残留的 uvicorn 孤儿进程（`--reload` 遗留 worker：杀主进程后 multiprocessing 子进程仍持有 socket，需按 `netstat -ano | findstr ":8000"` 逐个 taskkill）。
2. 本地后端必须 `--host 0.0.0.0`（不是 127.0.0.1），否则 WSL 容器无法访问——2026-09-21 实测 `127.0.0.1` 绑定时 WSL mirrored localhost 也连不上。
3. WSL TCP 中继重启（监听 8100，WSL 重启不自启）。**必须用 `setsid` 脱离会话**，普通 `nohup ... &` 会随 wsl.exe 会话退出被回收：
   ```powershell
   wsl sh -c "setsid nohup python3 /mnt/e/codex_workspace/agent_spot_welding/.worktrees/general-automl-annotation-20260902/temp_test/wsl_relay.py >/tmp/relay.log 2>&1 < /dev/null &"
   ```
4. 验证全链路：8443 页面 200 → 容器内 `host.docker.internal:8100` → Windows 后端 8000 → 网关 8444 `POST /portal/auth/login` 200。注意 WSL 冷启动后 mirrored 网络端口映射需数秒~数十秒才生效，连接拒绝先等再查。

## 3. 测试账号

- 标注员：`jingms / 12345678`（OAuth2 表单提交，首次输入失败清空重输即可）
- 管理端：admin（浏览器用 `127.0.0.1:5173`，规避 portal_session cookie 跨端口 CSRF 误拦）
- **管理员门户评审**：管理员用自己账号直接登录 8443 门户（后端 login 先匹配标注员账号，未命中再匹配 `role="admin"` 平台用户）

## 4. 近期完成的工作（2026-09-20 ~ 09-21，详见 DEVELOPMENT_PLAN.md 对应条目）

### A. 管理员登录标注员门户评审（验收/退回/批注）——今日最大功能

- 管理员在主平台回传验收面板点「在标注员门户查看明细」→ 门户 `?task=` 深链 → 管理员账号登录 → 直达该任务评审页。
- **AdminQueuePage**：只显示自己创建（`owner_id`）的未归档任务（含标注员、回传状态）；三项操作（合格验收/退回修改/批注）仅当存在 `state="pending"` 回传批次时可用，未回传禁用 + tooltip；验收生成数据版本、退回必填理由。
- **AdminReviewPage**：上一条/下一条（←/→）浏览样本（数据卡片网格 + 标注结果只读）+ 批注列表 + 输入框 **800ms 防抖自动保存**；无 pending 批次显示「任务未回传，无法批注」并禁用。
- 主后端 6 个 `/api/internal/portal/admin/*` 端点（scope `admin_review:read/write`，owner 校验，批注 `author_id`=管理员 users.id 复用 `AnnotationComment`）；网关 `api/admin.py` 7 条 `/portal/admin/*` 转发（kind 校验 403）。
- 管理员会话为无状态 JWT（TTL 30 分钟、无吊销能力）；admin 在门户不渲染通知收件箱。

### B. 回传验收面板重构（主平台）

- 批次卡片显示「任务名 (短 id) + 标注员 + 样本数 + 状态徽标」（后端 `list_return_batches` 新增 task/annotator 关联字段）。
- 验收页删除逐样本明细表（diff 仅用于计算空标签风险数）；摘要 + 三按钮无需长滚动。
- 「在标注员门户查看明细」按钮：`VITE_ANNOTATOR_PORTAL_URL` 或 `{protocol}//{hostname}:8443` + `?task=`。

### C. 聚类发现任务：标签改为聚类之后定义

- 向导第 2 步聚类**前**的「自定义标签 schema」编辑器删除；discovery 任务创建时后端生成零列占位 schema（`{任务名}-pending-labels`，避免 SQLite NOT NULL 列变更）。
- 聚类完成后（向导内、任务列表「配置策略」弹窗）出现 LabelSchemaEditor；保存策略时经 `label_schema_id` 换绑（更新端点用 `model_fields_set` 区分未提供/显式 null；binding 更新走 Core 层绕开 ORM 不可变事件）并重建冻结快照/config_hash。
- `label_schema_contract_from_snapshot` 增加 `allow_empty=config.cluster_discovery`。

### D. 任务生命周期与自动执行

- 预览完成后自动流转：手动任务自动「发布」（awaiting_annotation），自动任务自动「执行」；主平台「发布」「执行」按钮删除。
- 任务名/数据文件重名自动加后缀（`_unique_task_name` / `_unique_dataset_name`）。

### E. 门户体验修复（标注员侧）

- 标签框光标自动聚焦：切样本后 focus 第一个标签输入；标签框内 Enter=保存并下一条、Esc=移出恢复全局快捷键。
- 边界 null 校验修复：schema 显式 `null` 的 min/max/maxLength 导致「请输入十进制整数」误报（`!== undefined` → `!= null`，4 处）。
- 侧栏 200px（<1100px 时 190px）；分页控件 12px/5px 10px/4px 圆角，输入与说明文字同步缩小。
- 自动标注向导「最终预览」限高 340px 内部滚动（全量统计 JSON + 样本不再撑长页面）。

### F. 2026-09-19 主平台数据标注模块三页面重设计

统计条 + Segmented 页签合并任务/历史表格；操作列高频+「···」下拉；右栏 320px 运行中操作/执行结果；工作台两级顶栏 + 270px 折叠面板 + 字段卡片网格；向导第 2 步左表单右冻结契约摘要 + ClusterPreviewPanel 分栏。**浏览器实测未完成**（向导完整提交、策略配置弹窗、工作台布局，可用项目 `07531ee5` + 数据版本 `e1d8737d` 补验）。

### G. 2026-09-20 管理员门户孤儿任务过滤

- 根因：项目删除是硬删除（`projects.py` 只级联 TrainingJob/Experiment/Dataset/OrchestrationApp，不处理 GenericAnnotationTask），管理员门户列表只查 `owner_id`，出现主平台看不到的孤儿任务。
- 修复：`annotator_internal.py` 的 `internal_admin_tasks` 查询加 `GenericAnnotationTask.project_id.in_(select(Project.id))` 过滤；后端 24/24、回归 240/6、线上 4 个孤儿任务消失。

### H. 2026-09-20 「保存到数据管理」（已验收批次导出为数据集）

- 主平台回传验收面板 Drawer：`state === "accepted"` 批次显示导出区块（名称输入 +「检测标签并保存」）。
- 标签类型检测（`export_return_batch_preview`）：int/float 直接保存；string 列展示「标签值 → int 映射表」（枚举顺序优先、首次出现次之，从 0 编号），确认后保存（`EXPORT_LABEL_VALUE_UNMAPPED` 拒绝未映射值）。
- 错误码：EXPORT_BATCH_NOT_ACCEPTED(409) / ACCEPTED_DATASET_VERSION_NOT_FOUND(404) / EXPORT_NAME_REQUIRED(422)；i18n 中英文均已补。

### I. 2026-09-20 导出制品落真实文件（预览 Artifact file is missing 修复）

- 导出走 `build_artifact_service(db).create_from_file(...)` 落真实文件（storage_uri），预览/下载/物化与上传数据集完全一致。
- 文件类型自动跟随源制品（csv 标准库 / xlsx / parquet pandas，`_export_file_format` 回退 csv），名称自动带后缀且不可改；重名自动 `-2` 后缀（`_unique_export_dataset_name`）。
- 线上实测：任务「ass」147 条 int 标签导出 csv 后数据管理预览正常。

### J. 2026-09-20 标签列名中文检测（需重命名为英文才能导出）

- 后端：导出请求 `renames`（machine_key → 新列名），`_validate_export_renames` 校验英文标识符 `^[A-Za-z_][A-Za-z0-9_]*$` + 冲突检测；列定义/样本值/parse_contract.label_renames 均应用新名；`EXPORT_LABEL_NAME_INVALID`(422)。
- 前端：中文名列（非 ASCII）即使值类型为数值也不直接保存，确认区显示红色「中文名称 · 需改为英文」标签 + 英文名输入框；未全部填合法英文名前确认按钮禁用；`exportReturnBatchDataset` 三参调用。
- 验证：后端 18/18（含 4 种拒绝路径）、前端面板 8/8、全量 346/19 skipped、tsc 通过。**线上端到端未测**（原含已验收批次的 test 项目已删，admin 名下无回传批次）。

### K. 2026-09-21 门户 8443 恢复 + AutoML Accuracy 修复（并行会话）

- 8443 打不开：WSL 停止 + 后端误以 `127.0.0.1` 启动 + 中继未运行，按第 2 节恢复清单逐项恢复，全链路验证通过（见恢复清单实操记录）。
- AutoML 任务详情页模型结果 Accuracy 列显示 "-"：后端结果行只写 `score` 键，前端主表只查 `accuracy` 键；前端键列表扩为 `["accuracy","Accuracy","best_score","score"]`（详见 DEVELOPMENT_PLAN.md 2026-09-21 条目）。

### L. 2026-09-21 修复自动标注任务模型版本全部显示「未审批启用」

- 根因：双审批路径——`transition_model_version`（approve → enabled+approved 同设）vs 旧路径 `approve()`/`archive()`（只改 approval_status）；注册时 lifecycle_state 默认 pending_review，历史 84/86 版本处于 approved+pending_review 不一致，被自动标注 approved+enabled 双条件禁用。
- 修复：`model_registry.py` `approve()`/`archive()` 同步 lifecycle_state（早退分支治愈遗留 approved+pending_review 行，不碰 disabled/revoked）；`database_migrations.py` ensure_schema_compatibility 幂等回填 + Alembic 迁移 **`20260921_60`**（当前 head；upgrade_fixture/evidence_manifest/acceptance 脚本/test_database_production/test_inference_production_stack 的 head 常量已同步）。
- 本地库已治愈（86 approved 全部 enabled）；可选自动标注模型为 2 个 `automl-job - XGBoost` 平台版本，84 个 ONNX 上传版本按设计禁用（MODEL_SOURCE_UNSUPPORTED，仅支持平台 joblib）。
- 20260921_60 链头测试基线漂移同步修复：test_database_production `_seed_legacy_registry` 与 statistics migration 测试改 `sa.table()` Core 插入（仅旧修订列集，ORM 插入会带上新列 INSERT 失败）；Dockerfile 契约四文件 xgboost/catboost `--no-deps` 布局断言改行续行归一化；notification head 降级断言改通用 `Refusing destructive downgrade`。全量套件 1986 passed / 1 failed（notification，修复后单文件 8 passed 转绿）。

### M. 2026-09-21 自动标注任务 MODEL_INPUT_MISSING：创建时前置校验

- 现象：不启用弱监督（`clustering=false, strategy="model"`）创建任务成功，生成预览报 MODEL_INPUT_MISSING 且 details 为空。
- 根因：所选数据集为原始 90 列版本，模型训练于特征工程后的数据集版本（6fc046ee…，74 列 46 行），输入契约 73 列（14 原始 + 59 工程特征如 current_mean/voltage_pp/power_wld1）；模型包 preprocessing 仅含 `drop_rows_before_training`，不含特征工程变换，无法从原始列推导。**正确操作是选择模型训练时的数据集版本**。
- 修复：`generic_tasks.py` 新增 `_model_input_columns()`（读冻结的 conversion_metadata.input_contract，fallback feature_schema）+ `create_generic_task` 自动模式创建时即校验数据集 schema 覆盖输入契约，缺列 422 MODEL_INPUT_MISSING 列出缺失列前 10 个（弱监督/不启用两模式均覆盖）；`annotation_strategies.py` 预览错误信息携带缺失列；前端 `client.ts` `localizeApiError` 支持 `{message}` 占位符 + i18n 补词条。

### N. 2026-09-21 指派标注员信息增强 + 已指派排除 + 验收导出数据集补文件后缀

- `GET /api/annotators` 响应 items 增加 `email` 字段；`AssignmentDialog.tsx` 下拉选项富信息渲染（用户名加粗 + 邮箱 · 已审核通过 · 已授权本项目；antd optionRender），搜索同时匹配用户名与邮箱。
- 新增 `assignedIds` prop：`openAssignmentDialog` 并行拉取标注员列表与 `listTaskAssignments(task.id)`，下拉排除已指派 subject_id；抽屉内「已指派标注员（N）」信息块；全部已指派时空态提示「该项目标注员均已指派」。
- `export_return_batch_dataset` 导出名补源文件后缀（`验收结果集` → `验收结果集.csv`，用户已带后缀不重复加）；`_unique_export_dataset_name` 序号插在扩展名前（`验收结果集-2.csv`）。历史已导出名不回填。

### O. 2026-09-21 数据管理预览显示全部数据

- 根因：双重 10 行限制——后端 `preview_dataset` 固定 `df.head(10)` + 前端 `DataManagePage` 再 `slice(0, 10)`。
- 修复：`GET /datasets/{id}/preview` 新增可选 `limit` 参数（默认 10 不破坏既有调用方，`limit=0` 返回全部）；前端预览请求 `limit=0` 移除截断，模态框表格 60vh 双向滚动，顶部显示「共 N 行」。

### P. 2026-09-21 工作流画布与算子（并行会话）

- 全量算子契约审计与修复（82 个算子，operators/ 各文件 + 测试）。
- 多端口算子半圆端口超出节点圆角边框修复：176×176px 方卡 30px 圆角，端口限 16%–84% 竖直范围；3 输出 20/50/80%（30% 间距）、4 输出 20/40/60/80%（`CustomNode.tsx`，23 测试通过）。
- 工作流导出数据集版本失败修复：operator_id 以字符串写入 UUID 列触发 `'str' object has no attribute 'hex'`。
- QUALITY_WAVEFORM_INVALID_BASE64（row=46, field=cvei）：根因为输入 CSV 尾部 101 行空行（仅逗号），**属数据问题非代码缺陷**；missing_value_handler 只能处理数值列，解法为清理源 CSV 或加 row_filter。

### 运维知识（非代码）

- 新审核标注员不在指派下拉：需主平台 → 用户管理 → 标注员管理 → 授权项目（`project_annotator_grants` 表）；标注员须同时 active + 项目授权。

## 5. 关键工程约束（易踩坑）

1. **SQLite 不自动加列**：`create_all` 不给已有表加新列，必须同步 `ensure_schema_compatibility`（缺列 500）。
2. **CSRF 规则**：带 `Authorization` 头跳过 CSRF；纯 cookie 认证必须带 CSRF token；portal_session cookie 存在时 Bearer 请求可能误拦（管理端用 127.0.0.1 规避）。
3. **测试契约**：改 DOM/文案前先看 `*.test.tsx` 断言；新后端测试模块必须登记 `tests/week_manifest.py`。
4. **任务状态**：只有 `preview ready / 待标注 / 进行中` 可指派；指派下拉只显示 active + 项目授权标注员，且自动排除已指派过的 subject_id。
5. **自动标注模型输入契约**：所选数据集 schema 必须覆盖模型冻结的输入契约列（模型训练时的数据集版本，如特征工程后 74 列版本）；创建任务时后端前置校验，缺列 422 MODEL_INPUT_MISSING。自动标注仅支持 approved+enabled 的平台 joblib 版本。
6. **删除/归档任务**：portal 端点必须 404；运行中操作列表需 `archived_at.is_(None)` 过滤。
7. **NFKC 规范化**：标签输入值先 NFKC 再校验。
8. **错误信息本地化**：中文界面中文错误，i18n 字典在 `i18n/index.tsx` 的 `apiErrors`（支持 `{message}` 占位符透传后端详情）；门户 UI 中文、错误码英文大写。
9. **koa-connect 教训**：包装 Express 中间件丢 `ctx.state`，需原生 Koa 中间件。
10. **ORM 不可变事件**：`AnnotationTaskLabel` 直接改属性会触发 `IMMUTABLE_LABEL_HISTORY`；换绑走 Core 层 `update()`。
11. **门户网关契约**：网关端点转发时 scope（`admin_review:read/write`、`assignment:read/write` 等）与 claim（subject/admin_user_id）必须与主后端校验一致；管理员会话 JWT 复用 annotator_service 密钥。
12. **模型版本双审批语义**：approve 必须 approved+enabled 同设，archive 必须 archived；本地 UUID 存 CHAR(32) 无连字符 hex，直查需 `uuid.UUID(str).hex`。

## 6. 遗留问题与已知风险

1. **「开始手动标注」创建 run 失败（既有缺陷）**：`spotWeldQuality.ts` 的 `createQualityRun` 未携带 `X-Request-ID`/`Idempotency-Key` 头，待修复。
2. **主后端全量 18 个既有环境失败**（pyarrow/Alembic/Dockerfile 等，见第 2 节），与功能无关但影响全量绿灯。
3. **管理员门户会话无吊销**（无状态 JWT，TTL 30 分钟内有效）；批注保存失败的草稿切换样本时丢弃。
4. 样本字段极多任务（74+ 字段）：字段区容器内部滚动（一屏约束折衷）。
5. 工作树未提交：全部改动在 `general-automl-annotation-20260902` 上无 commit（交接时核对 `git status`）。
6. 管理员门户评审链路（登录→队列→批注→验收）已过单测，未做浏览器端到端实测（部署 8443 后用 admin 账号走一遍）。
7. 小屏（<960px）仅有 CSS 规则，未实机验证；2026-09-19 三页面重设计浏览器实测未完成（见 4.F）。
8. 标签列名中文重命名（4.J）线上端到端未实测：admin 名下「点焊」项目无回传批次，原 test 项目已删；中文列名场景仅有单测覆盖，下次有含中文标签列的已验收批次时在界面走一遍。
9. 「保存到数据管理」当前仅支持 csv 源实测（xlsx/parquet 路径有单测但本机缺 pyarrow，parquet 全量测试属既有环境失败）。
10. 全量套件未在 20260921_60 链头下完整重跑（并行会话编辑冲突风险）；历史导出数据集名无后缀不回填；工作流 QUALITY_WAVEFORM_INVALID_BASE64 属输入 CSV 尾部空行数据问题（清理源文件或加 row_filter，非代码缺陷）。

## 7. 日常工作流建议

1. 改动前看 `DEVELOPMENT_PLAN.md` 最新条目与 `AGENTS.md`。
2. 前端改动后：vitest + tsc + build，再 docker compose 部署 8443，浏览器实测（标注员 jingms / 管理员 admin）。
3. 每次变更后在 `DEVELOPMENT_PLAN.md` 顶部追加记录（`### 日期 标题` + 需求/实现/验证）。
4. 浏览器验证用 browser_use 子代理；`browser_evaluate` 单行且不含 `function` 关键字（箭头函数）；`select_option` 偶发 ref 失效但实际生效；新标签页无法携带 Authorization 头。

## 8. 关键文件速查

| 文件 | 说明 |
|---|---|
| `DEVELOPMENT_PLAN.md` | 全部变更记录（需求/实现/验证），交接第一入口 |
| `AGENTS.md` | 仓库级 agent 指令与自主执行边界 |
| `ml-platform/frontend/src/pages/DataAnnotationPage.tsx` | 主平台数据标注模块（任务列表/向导/工作台） |
| `ml-platform/frontend/src/components/AssignmentDialog.tsx` | 指派标注员对话框（富信息选项、已指派排除） |
| `ml-platform/frontend/src/components/LabelSchemaEditor.tsx` | 标签 schema 编辑器（向导蓝框/策略弹窗共用） |
| `ml-platform/frontend/src/pages/DataManagePage.tsx` | 数据管理页（预览 limit=0 全量行） |
| `ml-platform/backend/app/api/generic_tasks.py` | 任务创建/配置（模型输入契约前置校验、重名后缀） |
| `ml-platform/backend/app/services/model_registry.py` | 模型注册/审批（approve/archive 同步 lifecycle） |
| `ml-platform/frontend/src/components/ReturnAcceptancePanel.tsx` | 回传验收面板（批次关联+门户跳转+保存到数据管理导出） |
| `ml-platform/annotator/frontend/src/pages/AdminQueuePage.tsx` | 管理员评审任务列表（三项操作 gating） |
| `ml-platform/annotator/frontend/src/pages/AdminReviewPage.tsx` | 管理员批注工作区（浏览+自动保存） |
| `ml-platform/annotator/frontend/src/pages/TaskWorkspacePage.tsx` | 标注员工作区（手风琴侧栏、样本流、快捷键） |
| `ml-platform/annotator/frontend/src/styles.css` | Light Enterprise 主题（设计令牌+布局+admin 样式） |
| `ml-platform/annotator/backend/app/api/admin.py` | 网关管理员路由（/portal/admin/*） |
| `ml-platform/annotator/backend/app/services/session.py` | 网关会话（annotator/admin 双 kind principal） |
| `ml-platform/backend/app/api/annotator_internal.py` | 门户后端（auth、/api/internal/portal/*、admin/* 评审端点） |
| `ml-platform/backend/app/services/annotator_identity.py` | 门户身份（annotator DB 会话 + admin JWT + service token） |
| `ml-platform/backend/app/services/annotation_returns.py` | 回传批次（列表关联/验收/退回/diff/导出数据集：类型检测、string 映射、中文列名重命名、真实文件制品） |
| `ml-platform/backend/app/api/annotation_returns.py` | 回传/导出 HTTP 端点（export-preview / export-dataset） |
| `ml-platform/frontend/src/api/annotationReturns.ts` | 回传/导出前端 API（exportReturnBatchDataset 携带 renames） |
| `docs/technical-proposals/2026-09-01-general-automl-annotation-platform.md` | 总体技术方案（第 7 章为标注规则权威依据） |
| `docs/technical-proposals/2026-09-18-annotator-portal-redesign.md` | 门户重设计方案 |
| `design-showcase/annotator-portal/style-1-light-enterprise.html` | 门户视觉设计稿（实现基准） |
| `temp_test/wsl_relay.py` | WSL TCP 中继（重启后需手动重跑） |
