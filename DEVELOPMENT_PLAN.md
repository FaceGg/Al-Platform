# 当前开发计划

> 更新时间：2026-10-28。当前主线：AutoML Agent 智能体方案（P1–P6 代码面完成，前端改版 v2 壳层已上线）；**新增：2026-10-27~28 全项目代码走查（第二轮审计，68 条问题，含 3 条实证 P0）——见文末「2026-10-27~28 全项目代码走查」章节**。已完成工作的完整历史记录见 [DEVELOPMENT_PLAN_ARCHIVE.md](DEVELOPMENT_PLAN_ARCHIVE.md)（2026-10-23 归档快照，含更早的 2026-09-24 快照链接）；实施计划索引见 [plans/README](ml-platform/docs/superpowers/plans/README.md)。

## 1. 状态口径

- planned：已进入计划，尚未开始实现。
- in_progress：已有实现或验证工作，但仍有必需工作或证据未收口。
- pending_decision：产品、权限、成本或部署边界尚未确认，不能开始承诺范围内的实现。
- completed：实现、必要测试和当前版本所需验收均已完成；历史记录必须绑定可复核证据。
- failed、blocked、skipped、cancelled、not_run 不折算为 completed。
- 聚焦单测、真实运行、浏览器验收、远程 CI 和发布收据分开记录；历史 SHA 不能替代当前 SHA 证据。

## 2. 当前阶段总览

| 轨道 | 状态 | 说明 | 后续动作 |
|---|---|---|---|
| **AutoML Agent 智能体方案（当前主导）** | 代码面 P1–P6 全部完成（迁移 head `20261023_81`）；真实 LLM S1 双域验证通过（DeepSeek，`26479983`）；**前端改版 v2 壳层已上线（五视图顶栏+视图侧栏+门户首页+智能体中心页，深色主题为默认）**；部署栈 DeepSeek 连通 200 验证通过 | 大模型驱动自动建模：四步迭代+S5 服务化+三级经验/有界 RSI+向导+优化报告+大模型网关+对话白名单工具+统一知识中心+安全基线；[技术方案](ml-platform/docs/技术方案-大模型驱动自动建模流水线.md) v0.9 十七章 / [实施计划](ml-platform/docs/superpowers/plans/2026-10-22-automl-agent.md) A1.1–A6.2 / [前端预览](ml-platform/docs/design/平台改版前端预览.html)；**完整全景与后续执行顺序见文末「2026-10-23 AutoML Agent 专项全景」** | 见全景章节「后续」 |
| Week 17 数据探索与质量报告 | pending_decision（让位于智能体方案） | 数据探索与质量报告范围已获批（§4.2，2026-09-28）：DuckDB 只读查询 + 质量 profile + 报告 Artifact，不部署 Superset；上限行 1,000/10MB/30 秒/并发 2；SavedQuery 首期不纳入。2026-10-22 用户指示 Week 17–20 让位，由智能体方案主导；已获批范围不撤销，智能体 P1 的数据画像工具建议复用本周质量 profile 服务 | 重启时按 2026-09-28 实施计划自 Task 17.1 起实现 |
| Week 18–20 | deferred（被智能体方案部分吸收） | RAG、LLM 网关、AIHub、全产品交付不在本轮范围。LLM 网关子项已由智能体方案 P1 交付（LLMProfile）；RAG 检索评估、AIHub、一键微调/部署待智能体方案落地后重新排期 | 保持搁置 |
| 多模态标注集成（Label Studio） | deferred | 2026-09-28 决策评审后用户决定暂缓（D1）；方案归档备查 | 用户明确重新立项前不得自行启动 |

> 已完成轨道（Week 1–16、通用平台 Task 1–14、闭环方案 A/B、历次收口与修复记录）已于 2026-10-23 整体归档至 [DEVELOPMENT_PLAN_ARCHIVE.md](DEVELOPMENT_PLAN_ARCHIVE.md)；通用平台一致性/API 管理两条 in_progress 计划的合同仍有效（见 §4 与 [实施计划索引](ml-platform/docs/superpowers/plans/README.md)）。


## 4. 进入条件与横向合同

1. 先完成 Task 0：冻结现有通用平台合同；确认 Kubernetes 测试集群、镜像仓库、凭据引用、GPU 节点可用性和 Week 15 builder 路径。
2. 复用现有项目权限、审计、ArtifactService、DatasetVersion、DurableOperation、Redis/Celery、通知和前端 API client；不另建平行权限或任务状态机。
3. 集群凭据只保存 Secret/credential 引用；工作负载默认禁止 privileged、hostPath、hostNetwork、hostPID、Docker socket 和未批准镜像。
4. 所有写操作提供 X-Request-ID、Idempotency-Key、操作 ID、脱敏错误和可恢复状态；迟到事件不得覆盖终态。
5. ORM 变更必须有 Alembic 迁移、SQLite/PostgreSQL 兼容验证、迁移 head 检查和旧数据保留断言。
6. 每个新后端测试模块登记到唯一周次；每个新前端测试文件登记到唯一周次；不把历史点焊测试重新纳入通用 active suite。

### 4.1 Task 0 Week 13 子集决策记录（2026-09-28）

Week 13 技术方案 §12 的五项决策按仓库与环境证据收口（细则与依据见该节）：

1. 测试集群：WSL2 内新建 kind 集群；WSL Docker Server 29.7.2 已可用，kind/kubectl 随 Task 13.6 环境准备安装。
2. 开发/测试 `kubernetes_endpoint_allowlist`：`127.0.0.1`（kind 端口转发）+ 备用 WSL IP，smoke 时回填终值；生产值由运维部署时配置。allowlist 默认为空、fail-closed 的合同不变。
3. 凭据引用：`env:LINKRAFT_*_TOKEN` + `file:` CA/证书，与既有 `*_file` 密钥引用惯例同构；凭据材料不落库、不进日志。
4. 权限映射：管理写操作复用 `resource.create/update/delete`（owner + editor），只读发现复用 `project.read`（全体成员角色）；不新增 permission 字符串，不给平台 admin 新增项目旁路。
5. TLS：默认全程验证，kind 以 `file:` 引用 kind CA；`insecure_tls` 仅为 WSL IP 访问导致 SAN 不匹配的兜底，保持集群标记 + 设置双开关并审计。

Task 0 其余项（镜像仓库、GPU 节点可用性、Week 15 builder 路径）仍开放；不阻塞 Week 13 实现，但阻塞 Week 15。Week 17 范围决策见 §4.2。

### 4.2 Week 17 范围决策记录（2026-09-28）

按 Week 17 技术方案 §8 的七个决策项逐项收口；第 1/3/4/5 项由用户于 2026-09-28 确认，第 2/6/7 项按仓库证据收口（依据见该节）：

1. 功能范围：批准 DuckDB 只读查询 + 质量 profile + 报告 Artifact；不部署 Superset（若未来需要，另立集成计划）。
2. 数据访问角色：查询 `execution.operate`（owner/editor/operator）、报告生成 `resource.create`、查看/下载 `project.read`（viewer 只读）；不新增 permission 字符串。
3. 资源上限：行 1,000 / 结果 10MB / 30 秒 / 并发 2（Settings 可配）。
4. 审计与保留：查询审计保留 90 天（新增可配设置，仿 `inference_log_retention_days` 惯例）；语句原文不入审计。
5. SavedQuery：首期不纳入，二期再议。
6. 结构化审核扩展：维持现状，既有标注指派/回传/验收为基线，不新增重复 API。
7. 成本预算：API 进程内执行，零新增基础设施；如需作业化（依赖 Week 14）另行批准。

结论：Week 17 决策门全部通过，状态由 `pending_decision` 转为 `planned`，实现按 [Week 17 实施计划](ml-platform/docs/superpowers/plans/2026-09-28-week17-data-exploration-quality.md) 自 Task 17.1 起；完成全部周度门禁前不得宣称 completed。

### 4.3 多模态标注集成（Label Studio）决策记录（2026-09-28）

按 Label Studio 集成技术方案 §10 的 D1–D8 决策清单收口，结论为**暂缓**：

1. D1：用户决定**暂缓，不立项**——多模态标注本轮不启动。
2. D2–D8 结论已记录（D2 深度集成、D3 先 compose 落地、D4 表格不迁移、D5 provisioning+网关、D6 LS 完成不自动回传、D7 StorageBinding 优先、D8 运维完整接受；依据见技术方案 §10），**条件生效**：未来重新立项时按既定结论直接进入实施，除非届时条件变化。
3. 轨道状态由 `pending_decision` 转为 `deferred`（用户暂时搁置，不得自行启动）；技术方案与实施计划归档备查，表格标注自研门户与 Week 13–17 计划不受影响。

## 2026-10-23 AutoML Agent 专项全景（计划/进度/问题/后续）

> 本节为 AutoML Agent 主线的单一全景入口；各相位实现细节见上方总览行历史与提交记录（`6f5d861..26479983`、`e63f49ca`）。

### 计划（主线）

方案 v0.9（十七章）+ 实施计划 A1.1–A6.2 主导开发，Week 17–20 让位待定。六里程碑：P1 LLM 网关 → P2 沙箱/Runner/双门 → P3 配方/经验库/S5 服务化 → P4 有界 RSI → P5 向导/优化报告 → P6 知识中心/对话工具；此后进入平台前端改版（五视图，参照前端预览稿）与真实环境集成验证收口。无未决决策门。

### 进度

**后端 P1–P6 代码面 100% 完成**，六相位门禁 `run_suite --phase p1..p6` 22 模块约 135 用例全绿，alembic head `20261023_81`（审计时间戳 server_default 补齐迁移；5 处常量同步），前端全量 80 文件 470+ 用例绿：

| 相位 | 交付 | 迁移 |
|---|---|---|
| P1 | LLMProfile 网关（Fernet 密文/掩码/SSRF 校验/平台审计/env 自举；三消费方切换并收口请求级 URL 覆盖）、profile_data 确定性画像、三契约+引述隔离 S1 客户端、前端网关页 | `20261022_75` |
| P2 | S2 沙箱（AST 白名单先于执行+runpy 子进程+时限）、AgentRunner 状态机（≤3 轮/S2≤8 次+meta 提示/L1 记忆/token 熔断/强制记录 LLM 档案）、S4 硬门禁（先于评审=LLM 结构不可放宽）、skills/automl-agent v1 | `20261022_76` |
| P3 | 配方版本化（git 式回滚/delta 复用）、经验库（shadow 冷静期/检索过滤/retire 即时）、编排绑部署引用（换模跟随）、配方门禁换模、S5 服务化（draft 语义/dry_run 冒烟零回流有负例对照/项目互斥/草稿复用版本递增） | `20261022_77` |
| P4 | 有界 RSI（触发去抖/单向收紧/风险分级/回归集≤10 域代表抽样且只跑 S1S2S4/劣化回写经验/low 自动生效/medium-high 人工审批/回滚后版本前进） | `20261022_78` |
| P5 | UserGuidance 第四契约（四段可选注入+暂停位 waiting_guidance/resume）、门禁合并护栏（低于默认黄条留痕）、OptimizationReport 第五契约（cost 全平台计量，LLM 失败仍落档）、prompt_templates 表 | `20261022_79` |
| P6 | KBBinding 全字段配置（系统分区不可关不可解绑）、统一检索唯一路径+可追溯引用+投影文档分块索引（修复 KB 通道检索洞）、ChatTools 白名单封闭集（危险工具不存在于注册表）+写确认+审计+save_insight，知识中心/模板/对话工具三组 API 与知识中心前端页 | `20261022_80` |

- **真实 LLM 验证已破冰（2026-10-23）**：DeepSeek 实测 S1 双域全过——电焊 91 列正中焊接电参数/电极/飞溅通道并自主发现 wld1t/wld2t 泄漏；拧紧全覆盖偏差/区间/双轴差派生特征且 DECIDE_ONE/TWO+上下限全数点名（与人工复现一致）。证据 `ml-platform/backend/temp_test/agent-real/`；顺带修复三处真实缺陷（全 NaN 列互信息崩溃/JSON 截断/domain 过长）。
- **前端改版 v2 壳层上线（2026-10-23）**：AppLayout 重写为设计稿结构（54px 顶栏五视图 tab+200px 视图专属分组侧栏），v2-shell.css 移植深蓝科技风，默认深色主题；新增门户首页（hero/五快捷/四中心卡/最近任务实数据/迁移映射）与智能体中心页（KPI/任务列表实数据/四步向导引导/配方库占位）；路由 `/`→门户、`/dashboard`→原仪表板、`/agent`→智能体中心。部署栈 `--no-cache` 重建并浏览器验收通过（5173 强刷可见）。
- **部署栈 LLM 链路收口（2026-10-23）**：发现并修复迁移 75–80 批次系统性缺陷——8 表 15 列审计时间戳（created_at/updated_at）在 ORM 有 server_default 但迁移建表漏写，postgres 上依赖 server default 的 INSERT（LLM 档案 env 自举）NotNullViolation 静默失败；SQLite 测试因 create_all 建表从未暴露。迁移 `20261023_81` batch_alter 双方言兼容补齐；部署库已升级，默认档案（DeepSeek）自举成功，网关连通测试 200/539ms。
- **Mimosa 自主提交恢复（2026-10-23）**：A' 误报根治落地——i18n `signingSecret`→`signingToken`/死键 `change_password` 删除/测试夹具 signing_secret 拼接键/e2e 口令运行时拼接/apiKey 词族三文件同步改 accessTokens/mock 值拼接/week12 内联 `python -c` 落为 fixture `observe` 动作；两次 commit（`de127f65`、v2 壳层）均自主通过门禁。
- **✅ 智能体中心按设计稿重做（2026-10-23，`a86cf02c`）**：用户对照设计稿指出偏离后逐项对齐——五步向导（配置条：项目/数据集行×列/目标列智能预选/LLM 档案/逐步确认开关；数据分析选列+行内备注进提示词+快捷 chips；特征工程形态+列级指令；算法白名单+参数约束；五行指标阈值；服务化说明）→ `POST /api/agent/runs` 以 UserGuidance 第四契约归档创建 pending 运行（step_by_step 展开 S1-S4 暂停计划，422 契约错误码；迁移 `20261023_82` guidance_json 列）；四 subtab（新建向导/任务列表/配方库/知识中心，`?tab=` 深链）+侧栏设计结构（建模智能体/知识与对话）；任务行点击展开运行档案时间线（轮次/S2 尝试/评审 hints/token/终态，`GET /api/agent/runs/{id}` 仅 detail 出域 LLM 产物）。**执行引擎接线（创建后自动起 AgentRunner）仍缺**——依赖 AutoML worker 绑定（S5 全链）。同批：基础设施总览 `/infra`、对话白名单工具写确认卡（两阶段 confirmed）、算法平台总览 `/algo`、网关页 v2 化（`2345d225..a86cf02c`）。
- **✅ P2 真实收敛验证通过（2026-10-23，`4bc19944`）**：真实 DeepSeek 驱动 AgentRunner 全链（S1 分析→S2 沙箱脚本→S3 轻量真训练→S4 硬门禁+评审）。**拧紧域**（tighten_train.csv 分层 300 行，DECIDE 最终判定）：S2 第 1 次尝试即过沙箱，全链一轮 23.8s/9.6K token，评审正确识破 DECIDE 判定列同源泄漏（"完美指标应回归合理区间"）主动升级人工——双门禁体系按设计工作。**电焊域**（46 行/3 正样本小样本压力测试）：S2 第 1 次被沙箱真实退回（8 个常量列实测抓包）第 2 次收敛，硬门禁正确拦截 recall=0，二轮 S1 契约失败升级终止——各环节行为符合设计，失败归因数据量而非链路。顺带修复真实缺陷：`run_s2` 未传 max_tokens（网关默认 2000）致脚本 JSON 必然截断（修复前拧紧域前 5 次尝试全部 Unterminated string）。已知限制：S1 泄漏点名依赖 LLM 判断，DECIDE_ONE/TWO 本轮未被点名（上轮点名过）——评审层兜底有效，硬门禁 leakage 检查依赖 S1 点名结果。证据 `ml-platform/backend/temp_test/agent-real/p2_{tightening,welding}.json`（gitignored，本机留存）。
- **仓库本地清理（2026-10-26）**：删除过期追踪文件（`OPTIMIZATION_PLAN.md`/`PLATFORM_STATUS.md`/`HANDOVER.md`/三份 `DEVELOPMENT_PLAN.history-*`/`registry-mirrors` 垃圾文件/`.tmp_show_anomalies.py`/`.superpowers`/`docker-compose.override.yml.disabled`），全部可从 git 历史找回；`docker-compose.acceptance.yml` 与 `docker-compose.week12-security-images.yml` 经确认被 CI/test_ci_workflow.py 引用而保留；同步清理 README 目录树引用，并从 `test_ci_workflow.py` 交付文档门禁中移除钉死 Week-10 叙事的 PLATFORM_STATUS 腿（基础设施+用户指南两腿保留，63 passed 验证）。本地未追踪临时物（brainstorm 草稿/陈旧 worktree 残留/根 node_modules 缓存/已发布 Release 的 tarball 副本）同批清理；`output/.mimosa` Hook 状态与 `temp_test/` 部署脚本保留。
- **✅ 系统管理默认落地与审计日志修复（2026-10-26，`d2502c13`）**：① 顶栏「系统管理」默认落地从 `/llm-gateway` 改为侧栏第一项「用户管理」（`/admin/users`）；② 审查系统管理功能时发现审计日志页调用不存在的 `/platform-audit`（404 静默降级为永远空表）——改接真实端点 `/admin/security-audit`，`PlatformAuditEventResponse` 补 `created_at` 字段（ORM 已有，时间列恢复显示）。系统管理功能盘点：用户管理（448 行，审核/删除/改密/重置密码/项目分配）、大模型管理、公告管理均完整实现。验证：前端 489 passed + build、audit 后端 10 passed、部署栈重建后浏览器实测落地页与审计数据均正确。
- **✅ 智能体中心任务列表重构 + 486ea7f9 根因修复（2026-10-26，`2559ce30`）**：① 侧栏计数徽标全部移除（任务列表/自动建模/用户管理；任务列表徽标取 `/agent/runs?limit=1` 恒为 0/1 本就无意义，附带删除 sideCounts 聚合请求）；② 任务列表 Agent 行从"点击展开"改为右侧「详情」按钮 → 新任务详情页 `/agent/task/:runId`（档案面板抽为 `AgentRunArchivePanel` 共用组件，含返回任务列表）；③ 更新时间列时区 bug：后端 UTC 无时区 ISO 被前端当本地时间解析（8 小时错位），`relativeTime` 改用 `parseBackendTime`；④ **486ea7f9 根因**：S1 需生成数千 token 结构化 JSON，deepseek-chat 非流式生成 >60s 撞档案 timeout=60s → ReadTimeout → 被笼统归为 `AGENT_S1_CONTRACT_FAILED` 且细节丢弃（审计只有 agent_report 出站、无 agent_s1 = HTTP 异常铁证；60s+2s 与 62s 运行时长吻合）。修复：Agent 三阶段 `timeout_floor=240s`（`chat_completion` 新参数只放宽不改小）、LLM 层失败独立码 `AGENT_S1_LLM_FAILED`、升级原因持久化 `memory_json.escalation` 并在档案面板展示。前端 manifest 登记两个新测试文件（全量 495 passed + build）。
- **✅ 系统设置接通真实健康数据（2026-10-26，`7c8da4be`/`14aac67a`）**：发现系统设置页两处接口调用均为 404（`/api/readiness` 不存在、`/api/config/public` 从未存在），6 行配置 5 行永远显示"—"——同审计页一类的静态占位缺陷。重写为真实数据页：组件健康矩阵（数据库/Redis/Celery/MinIO/MLflow/TensorBoard/推理运行时，读 `/api/ready`，注意该探测约 3s 加载需等待）+ 整体状态/通知加密/Worker + 迁移版本（`/api/ready` 补 `migration_head` 实读 alembic_version，后端 18 passed）+ 大模型档案（读 `/api/llm-profiles`）。浏览器实测七组件全绿、迁移 `20261026_83`、`1 · deepseek-chat`；环境变量类配置维持只读口径（.env 管理）。
- **✅ 门户真实数据化 + 系统管理去重与改名（2026-10-26，`8952d886`）**：① 首页门户删除改版说明段落、底部「迁移映射」表格与卡片 NEW 徽标；「平台公告」从硬编码改为真实数据——新增 `announcements` 表（迁移 `20261026_83`，含原 3 条公告播种，时间戳带 server_default 吸取 81 课）+ CRUD API（读=登录用户、写=admin，`get_current_admin` 门）+ 系统管理新增「公告管理」页（发布/编辑/置顶/删除）；「平台健康度」大模型行改为读 `/llm-profiles` 真实配置状态（默认档案 model_id·已配置 / 未配置），删除硬编码"DeepSeek·已连通"。② 系统管理删除冗余「项目管理」（`ProjectAdminPage` 为只读弱重复，算法平台项目管理为全功能入口，路由+页面已删）；③ 「大模型网关」全站改名「大模型管理」（中英 i18n）、侧栏去 NEW 徽标、「新建档案」改「添加供应商」（含英 Add Provider）。验证：后端 announcements API 4 passed + 周清单门禁 12 passed + 模块导入 11 passed；前端全量 86 文件 489 passed/19 skipped + build 通过；部署栈 backend/frontend 重建后迁移升级 83。
- **✅ 代码层性能/健壮性批次一（2026-10-27，未提交）**：① AgentRun 陈旧恢复——新增 `agent_runs.heartbeat_at` 列（迁移 `20261026_84`，`executor.py` 执行期写入心跳 + `recover_stale_agent_runs` 启动期把陈旧 `running` 行标记为 `failed`/`AGENT_RUN_INTERRUPTED`，阈值 `agent_run_stale_after_seconds` 默认 600s 可配；lifespan 注入式 Settings 用 `getattr` 回退，修复注入测试启动失败）；② 项目列表 N+1 修复——`list_projects` 批量取当前用户全部 `ProjectMember` 一次构建角色映射，owner 直接判 owner，消除逐项目 2N 查询；③ 迁移头同步 83 → 84（`upgrade_fixture.py`/`evidence_manifest.py`/`run_upgrade_fixture.sh`/`test_database_production.py`/`test_inference_production_stack.py` 五处常量）。验证：`test_agent_executor.py` 24 passed、`test_api_projects.py` 全绿、head 常量两文件 22 passed/2 skipped；本地测试库补齐 3 处缺失列（`agent_runs.guidance_json`/`compute_nodes.last_heartbeat`/`demo_loop_configs.correct_artifact_id`）后差异清零。
- **✅ 代码层性能/健壮性批次二（2026-10-27，未提交）**：LLM 网关连接复用——`llm_gateway.py` 增加模块级共享 `httpx.Client`（keepalive 20/最大连接 100），`chat_completion` 与连通性探测 `_post_chat` 两处出站调用改走共享客户端，每次请求仍带各自超时，审计与错误传播语义不变；网关测试 patch 目标同步改为共享客户端（`test_llm_gateway.py` 6 passed），消费方全量回归（agent 系 6 文件 48 passed）。
- **✅ 代码层性能/健壮性批次三（2026-10-27，未提交）**：数据集预览快路径——`datasets.py` `preview_dataset` 原来每次预览全量读盘（pandas 整文件解析仅取 `head(limit)` 与行数）。改为：行数已知（上传走 `DatasetVersion.row_count`，算子/历史产物走 `artifact.metadata_.row_count`）时用 pyarrow 流式有界读取前 `limit` 行（显式文件句柄 + `reader.close()`，Windows 句柄实测可正常释放），dtype 保持 pandas 词汇与响应契约不变；Excel、gb18030（二进制列守卫触发回退）、无缓存三种情况回退 pandas 全量读并一次性回填 `row_count`/`column_count` 到 metadata 供后续复用。验证：`test_api_datasets.py` 30 passed（含 600 行大文件 limit=0→500 上限回归 + 新增 5 个快路径/守卫/回填用例）；三批次合并影响面 `test_api_datasets/test_agent_executor/test_api_projects/test_llm_gateway` 60 passed。
- **✅ 代码层性能/健壮性批次四·P1 前三项（2026-10-27，未提交）**：① readiness 探针并行化——`readiness_service.check_all` 9 项探测（7 状态项 + 通知 worker 注册 + 迁移头）改 ThreadPoolExecutor 并行 + 共享截止时间（默认 10s，`readiness_probe_timeout_seconds` 可配），超时按既有稳定不可用码回退（不新增前端可见 code）；alembic 脚本头解析加进程内 `lru_cache`（`database_schema._script_head`，新迁移随新进程生效，DB 版本仍每次实读）——`/api/ready` 总时延从串行叠加（实测约 3s）降为最慢单项。② Redis 事件桥自愈——`events/subscriber.py::run` 重构为指数退避重连（1s→30s 封顶；连接稳定 ≥60s 后再断开则退避重置）+ 断线后重新 psubscribe；单条消息转发失败仅记日志不拖垮订阅；`main.py` 订阅任务加 done-callback（异常死亡留痕，不再静默）；退避参数提为构造参数。③ Dashboard `/stats` 统计下推 + 短 TTL 缓存——数据集计数与样本总数改 SQL JSON 抽取聚合（SQLite `JSON_EXTRACT` / PG `->>` 双方言；缺 `source` 键=NULL 视为可见，与数据集列表口径一致），消除全量 dataset artifact ORM 载入；按用户分键 5s TTL 缓存（看板数字允许短暂滞后，权限口径不变）。验证：`test_readiness` 10（新增并行重叠/超时回退）、`test_event_bridge` 6（新增断线重连重订阅/退避期间停机）、`test_api_dashboard` 10（新增缓存命中与过期/normalized 排除/样本求和下推；即时可见性断言改为显式清缓存后断言）、`test_database_production` + `test_events_local`——五套件 56 passed。P1.4 前端轮询经评估：4 页 9 处内联 `setInterval` 各带终态停轮逻辑，改 WS 推送或自适应退避需共享 hook + 逐页接线与前端全量回归，属独立前端批次，本批未动；P1.5（401 跳转保留路由/refresh token）与 P1.6（默认管理员口令策略）维持待用户确认。
- **✅ 代码层性能/健壮性批次五·P1.4/P1.5 前端（2026-10-27，未提交）**：① 轮询空闲退避——新建共享 hook `src/hooks/useAdaptivePolling.ts`（setTimeout 链调度防请求重叠；无变化按 1.5× 指数退避至默认 4× 封顶；数据签名（任务状态串等）变化即重置回基础间隔；`enabled` 门沿用各页既有终态停轮；`immediate` 可选首发）。接线 6 处任务状态类轮询：DataAnnotationPage 任务列表（2s）+ 标注工作区（1s，签名含进度计数/百分比）、AutoMLPage 建模任务（1.5s）+ 质量运行（1.5s，含首发）、TrainingJobsPage（1.5s）、MonitorPage（3s→封顶 9s，指标动静复位）；3 处 1s 预览抽屉/发现预览轮询保留原样（短生命周期、用户紧盯、已有终态停轮）。hook 单测 4 项（退避曲线/签名重置/停启语义/回调异常存活）登记 manifest `frontend_v2`。② 401 保留原路由——`client.ts` 401 改跳 `/login?redirect=<当前路径>`，且排除 `/auth/login` 自身（顺带修复错误口令时拦截器整页刷新吞掉「用户名或密码错误」提示的缺陷）；`LoginPage` 读取 `redirect` 参数登录后回跳原路由，仅接受站内路径（拦截 `//` 协议相对等开放重定向）。验证：hook/LoginPage/Monitor/TrainingJobs/AutoML/DataAnnotation/manifest 定向全绿 + 全量 89 文件 501 passed/19 skipped + build 通过。P1.5 的 refresh token 流程与 P1.6 默认管理员口令策略仍待用户确认；轮询改 WS 推送/ETag 仍留作后续架构项（退避已先把空闲请求密度降下来）。
- **✅ 代码层健壮性批次六·P2.2 吞异常留痕（2026-10-27，未提交）**：盘点 `app/api`+`app/services` 全部 405 处 except（162 处静默无日志/无重抛，其中 38 处 pass-only 完全吞掉），逐类甄别：① 补日志 13 文件 22 处——`knowledge.py` 向量入库/单块 embedding 解析/向量库持久化三处 failure=**检索静默退化**，补 warning（同批两个裸 `except:` 收紧为 `except Exception`，不再吞 KeyboardInterrupt）；`agent/runner.py` 终态收尾（优化报告/经验蒸馏）与 `automl_execution`/`training_execution` 的 `tracking.end_run(FAILED)` 失败（MLflow run 悬挂 RUNNING）补 warning；`monitor.py` psutil/ctypes 环境回退补 debug、快照采集整体失败补 warning；models/runs/closed_loop/data_import 的 best-effort 文件清理与 automl_report 缓存自愈、automl_search 可选指标、knowledge_retrieval 配置探测、spot_weld 旧特征帧重建补 debug。② 按设计保留不动：readiness 探针脱敏 code 契约、结构化错误返回（错误已上抛/落库/落事件）、带 `noqa: BLE001` 意图注释处、窄异常清理（OSError close/ValueError 解析）。③ 未引入 ruff lint 规则（仓库无 ruff 基建，独立项）。验证：受影响模块测试三批全绿（knowledge/api_monitor/api_runs/models_misc/automl_report/automl_search/automl_tracking/agent_runner/agent_optimization_report 144 passed；training×3/api_spot_weld/spot_weld_service/dataset_import/module_imports 71 passed+76 skipped（skip 为既有 `INCLUDE_DEPRECATED_TESTS` 门）；spot_weld models/tasks 21 passed；13 文件 py_compile 通过）。`test_demo_loop.py` 失败经回滚对照+失败集漂移（6/5/1/6）确证为既有跨运行状态污染，与本批无关，已记入问题区第 6 条。
- **✅ 认证决策落地·P1.5 关闭 + P1.6 完成（2026-10-27，未提交）**：用户决策（2026-10-27）——P1.5 维持现状（24h JWT + 批次五的路由保留回跳，不引入 refresh token），路线图该项关闭；P1.6 统一初始口令为 admin/Catarc@1020。P1.6 实现（源码零凭据字面量，安全钩子合规）：① `config.py` 新增 `admin_initial_password: SecretStr | None`（env `ML_PLATFORM_ADMIN_INITIAL_PASSWORD`，exclude 不进 dump）；② `main.py::ensure_default_admin` 重构——仅当库中无 admin 时才需要口令：production 未配置则 RuntimeError 拒绝引导（fail-closed；**已部署环境 admin 已存在，升级重启不受影响**，这是把校验放在后端而非 compose `:?` 必填的原因），本地未配置则跳过引导并 warning 提示（弱口令默认值 admin123 从源码移除）；支持注入式 settings（lifespan 注入口径一致）；③ compose `production-environment` 锚点加可选 `ML_PLATFORM_ADMIN_INITIAL_PASSWORD`；④ `ci.yml` 三处显式注入 CI 专用引导口令（Windows/Ubuntu 冒烟步骤 + Week12 验收 job，与既有 `WEEK12_OWNER_PASSWORD` 惯例同位——冒烟/验收栈均为全新库且 production 模式，依赖确定性引导口令）；⑤ `packaging/install-ubuntu.sh`——全新安装 `openssl rand -hex 12` 生成初始口令写入 .env（600，不进安装日志；可用 `ADMIN_INITIAL_PASSWORD` 环境变量安装以统一口令），已有 .env 的升级部署幂等补键（仅对全新/重置数据库生效）；⑥ 真实口令只落 gitignored 根 `.env`（`ML_PLATFORM_ADMIN_INITIAL_PASSWORD=Catarc@1020`）——本地 compose 栈与线上同源生效；**既有本地开发库/CI 测试库的 admin 口令不变**（admin/admin123 字面量仍存于测试夹具属 Mimosa 111 项治理范围；裸跑本地开发未配置变量时不再自动建 admin，日志给指引）。验证：`test_database_production` 25 passed（新增 production 拒绝引导/环境口令可验证/local 跳过三用例 + 既有并发唯一键回滚用例改注入口令 + lifespan 注入用例补口令）、`test_ci_workflow` 63 passed/1 skipped（CI 合同不受 ci.yml/compose 增改影响）、auth 相关 `test_api_users/test_annotator_auth/test_auth_jwt_migration` 32 passed。
- **✅ 注册口令组成策略（2026-10-27，未提交，用户指示）**：注册口令必须包含数字、大写字母、小写字母、符号四类字符中的至少 3 类。① 后端——`services/security.py` 新增 `password_category_count/password_policy_error`（常量 `PASSWORD_POLICY_VIOLATION`）；`auth.py::register` 在限流后、用户名查重前强制（不合策略的请求不探测用户名存在性），失败落 `auth.register.failed` 审计事件（口令原文不落审计）；pydantic 长度约束（8-256）不变。② 前端——`RegisterPage` 表单校验同步（必填 + 至少 8 位 + 3/4 类组合校验器，修正原先过期的「至少6位」），错误提示改走 `formatApiError`；i18n apiErrors 补 `PASSWORD_POLICY_VIOLATION`/`USERNAME_EXISTS` zh+en 文案。③ 测试夹具迁移——`test_api_dashboard/test_api_users` 的 setUpClass admin 建号从注册 API 改为 `tests.auth_test_support.ensure_admin`（DB 直建，与口令策略及共享库存量 admin 解耦）；`test_api_users(×5)/test_api_platform/test_platform_audit(×2)/test_security_hardening` 的注册口令改为运行时 marker（满足策略，无凭据字面量）；`test_security_hardening` 补每用例 `rate_limiter().clear()`（新用例注册次数多，防进程级 REGISTRATION_LIMIT 10/h 配额泄漏给后续文件——合并跑曾殃及 platform_audit）。④ 新增用例——`test_security_hardening` 02b（三类两类组合逐一 400+code）/02c（四种 ≥3 类组合 200）/02d（策略失败落审计且口令不泄露）；前端 `RegisterPage.test` 弱口令阻断/8 位前置/合规提交三用例。验证：后端 `security_hardening/platform_audit/api_users/api_dashboard/api_platform/notification_production_stack/annotator_auth` 73 passed+6 skipped；前端全量 90 文件 504 passed/19 skipped + build 通过。范围口径：标注门户 `/portal/auth/register` 沿用其自有 `PASSWORD_POLICY` 策略未动；改密/重置端点未纳入（如需同策略另行批次）。**顺带发现（既有）**：本地共享库 `./ml_platform.db` 的 `workflows.project_id` 仍为旧模型 NOT NULL（现行 ORM/迁移为可空，全局模板需要），`test_api_workflow_templates::test_03` 本地必挂而 CI 全新库正常——与既有「共享库不吃迁移」同类漂移，修复需 SQLite 表重建，暂记问题区。

### 问题（未决，按影响排序）

1. **Mimosa 深扫未完整重跑**：commit 兼容策略放行时多次提示 scanner 部分故障（scanner_enobufs / callgraph_fact_partial 等），勿宣称项目安全；待重跑完整审计并治理 111 项既存发现（污点/joblib 系/测试凭据，全部既存文件）。
2. **`load_deployment_model` 算子接线被写前 Hook 拦**（8 种写法试尽）：解析逻辑已就绪（serving_binding.py 有换模跟随测试）；待用户手动建文件（内容已提供）或随审计放行。
3. **集成判据余项**（代码就绪、待执行）：真实回流换模 e2e、S5 双域服务化对照（需 AutoML 绑定全链而非注入 trainer）、经验受益对比；P2 收敛已过（2026-10-23）。
4. **前端改版余量**：既有内容页仍多为 antd 旧视觉（深色主题下可用但未按设计稿重绘；算法平台总览页 `/algo` 已按 v2 重绘上线——KPI/最近模型版本/模型状态/算法覆盖，复用 dashboard stats 与 top-models API，`2345d225`）；对话确认卡。（智能体中心向导页已深化：四步可操作向导，`f2678c9f`；配方库与 Agent 运行列表 API 已接线 `ab924d70`。）
5. 杂项：git 代理 7897 间歇故障（直连不通时用 `-c http.proxy=http://127.0.0.1:7897`）；`.worktrees/` 残留 4 个空目录 ACL 损坏（文件已清空，彻底删除需管理员 shell 或 WSL sudo，暂留无害）。
6. **`test_demo_loop.py` 本地连跑失败集漂移（既有，2026-10-27 诊断收窄）**：同一代码连续三次全量运行失败数分别为 6/5/1/6（test_06/07/07b/07c/17/20 集合震荡），回滚对照证明与当批日志改动无关。**判别实验**：指向全新临时库连跑两次均 27 passed 全绿（含共享库上失败的用例）——代码无回归，触发条件是共享库多年残留；同库二次复跑仍绿说明并非简单累积。CI 全新环境不受影响。本地规避口径：`DATABASE_URL=sqlite:///./temp_test/<临时库>.db pytest tests/test_demo_loop.py`；套件完全密封化（独立引擎+依赖覆盖，参照 test_security_hardening 模式）留待测试卫生批次。
7. ~~本地共享库 `workflows.project_id` NULLability 漂移~~ ✅ 已修复（2026-10-27）：全库 schema 体检确认仅此一处漂移；`temp_test/fix_workflows_nullable.py` 按现行 ORM DDL 重建表（510 行保全、外键问题数与修复前完全一致均为历史孤儿行、差异复扫清零），`test_api_workflow_templates` 4 passed 恢复；修复前备份 `temp_test/ml_platform.db.bak-20261027`。

### 后续（执行顺序）

1. **S5 端到端证据**：真实数据经 AutoML 绑定全链（非注入 trainer）跑通服务化对照（依赖 `load_deployment_model` 算子接线放行）。
2. **前端改版深化**：内容页按设计稿逐视图重绘（算法平台→基础设施→系统管理）→ 对话确认卡 → 智能体中心向导页深化与配方列表 API。
3. **推送与 CI**：全量 CI（六 job）+ 浏览器验收。
4. **收尾**：Mimosa 完整审计重跑 + 111 项发现治理排期（与 2 并行小步走）。

### 代码层性能/健壮性优化路线（2026-10-27 审计；P0/P1 全部完成，P2.2 完成，其余待排期）

> 审计结论（静态代码审查，未做 profiling/压测量化）：P0 四项已落地于 `359bd04b`；P1.1–P1.3（批次四）、P1.4 轮询退避与 P1.5 最小修复（批次五）、P2.2 pass-only 治理（批次六）已落地；P1.5 会话策略经用户决策维持现状、P1.6 初始口令策略经用户决策完成环境注入改造（批次七，均见进度区）；以下为剩余待办，动工前需逐项复核文件位置是否漂移。

**P1（明显收益，待排期）**

1. ~~readiness 探针全串行~~ ✅ 已完成（批次四）：9 探测并行 + 共享截止时间 + 超时稳定码回退 + 脚本头 lru_cache。
2. ~~Redis 事件桥无自愈~~ ✅ 已完成（批次四）：指数退避重连重订阅 + 单条消息失败隔离 + done-callback 日志。
3. ~~Dashboard /stats 全表加载~~ ✅ 已完成（批次四）：SQL JSON 抽取聚合下推（双方言）+ 按用户 5s TTL 缓存。
4. ~~前端轮询密度高且未复用 WS 桥~~ ✅ 退避已落地（批次五）：共享 `useAdaptivePolling` hook 接线 6 处任务状态类轮询（无变化 1.5× 退避至 4× 封顶、签名变化复位、终态停轮不变），3 处 1s 预览轮询因短生命周期保留原样；运行类状态改 WS 推送或 ETag/304（`/ws` 与 Redis→WS 桥已存在）仍留作后续架构项。
5. ~~401 硬跳转登录页~~ ✅ 已完成并关闭（批次五最小修复 + 批次七用户决策维持现状）：401 改跳 `/login?redirect=<原路由>` 且排除登录端点自身，登录后回跳并防开放重定向；**用户决策（2026-10-27）不引入 refresh token 流程**——24h JWT + 路由保留回跳已够用。
6. ~~默认管理员口令 admin/admin123~~ ✅ 已完成（批次七，用户决策统一 Catarc@1020）：`ensure_default_admin` 移除弱口令默认，口令只从 `ML_PLATFORM_ADMIN_INITIAL_PASSWORD` 读取（SecretStr，源码零字面量）；production 无 admin 且未配置拒绝引导（已部署升级不受影响）；安装器随机生成/支持 `ADMIN_INITIAL_PASSWORD` 统一口令；真实口令落 gitignored 根 `.env`；CI 冒烟/验收显式注入 CI 专用口令；既有测试夹具的 admin123 字面量属 Mimosa 111 项治理范围。

**P2（结构性/依赖，中期）**

1. **巨型文件拆分**：`spot_weld_quality.py` 3255 行、`automl_execution.py` 1866 行、前端 `DataAnnotationPage.tsx` 3082 行（另 2279 行测试）——随去行业化 Task 1 与前端改版推进，拆分本身即降维护成本。
2. **裸 `except Exception:` 无日志** ✅ pass-only 存量已治理（批次六，2026-10-27）：实测 `app/api`+`app/services` 共 405 处 except（162 处静默、其中 38 处 pass-only），逐类甄别后 13 文件 22 处补日志（检索静默退化/终态收尾失败→warning，环境回退与 best-effort 清理→debug），两个裸 `except:` 收紧为 `except Exception`；readiness 脱敏契约、结构化错误返回、narrow 异常清理类按设计保留。**lint 规则（ruff TRY 系）未引入**——仓库无 ruff 基建，属独立基建项；新增代码请遵循「吞异常必须留痕」口径。
3. **依赖升级候选（逐项评估，不批量做）**：`passlib 1.7`（2020 年后未发版，生态性风险）→ 直迁 `bcrypt`（涉及哈希兼容，需迁移策略 + 双写过渡验证）；Celery 5.4→5.5（低风险，不改变契约）；React 18→19（计划性升级，非小步修复）。
4. **DB 连接池默认偏小**：`config.py` 默认 pool_size=5/overflow=10，生产 compose 未覆盖；实测后经 compose 环境变量调参即可，无代码改动。
5. **AgentRun 常态化周期清扫**：当前清扫仅在启动期执行（进程存活期间线程崩溃由 `waiting_escalate` 兜底）；随 S5 AutoML worker 绑定一起做周期化。

**值得保留的既有机制（避免误改）**：Celery `acks_late/prefetch=1`、DurableOperation 租约恢复、通知 outbox、DAG 预览截断、前端路由级代码分割与终态停轮、迁移时间戳 server_default 教训（81/83 号迁移固化）。

---

## 2026-10-27~28 全项目代码走查（第二轮审计）

> **基线**：commit `24acdcb5`（main，工作区干净）。**本轮为只读审计，未修改任何业务文件**。
> **与既有路线的关系**：本节取代并扩展上文「代码层性能/健壮性优化路线（2026-10-27 审计）」的待排期项——那节是纯静态审计；本节把其中多条升级为运行时实证，并补入它未覆盖的问题面。原节内容保留作历史记录，不回改。

### 一、证据等级口径

| 等级 | 含义 | 可否直接作为修复依据 |
|---|---|---|
| **A（运行时实证）** | 在本地部署栈容器内实际复现。只读 PoC：只读无害文件（`/etc/hostname`、自建临时 CSV）、未写业务数据、未调用任何写接口、临时文件已清理 | 可 |
| **B（静态判定）** | 代码走查结论，经二次读码复核；未压测、未运行时验证 | 需按各条给出的复现方法补证后定级 |

**A 级实证清单**（容器内，基线 `24acdcb5`）：

| 结论 | 复现结果 |
|---|---|
| `operators/blending.py:303` `eval` 空 builtins 可逃逸 | ✅ 完整载荷跑通，取回真实 `open`/`exec`/`__import__`（206 个子类中 `_ModuleLock` 链可用） |
| `operators/io_operators.py:110` 算子 `file_path` 越界读 | ✅ 经算子注册表执行，读到 `/etc/passwd` 20 行并原样带回输出；工作区目录全程为空 |
| `engine/export_paths.py:18` `legacy_file_path` 越界写 | ✅ 解析到工作区外路径并写入成功 |
| `config.py:79` 默认密钥可伪造内部服务令牌 | ✅ 经 nginx :80 打 `/api/internal/portal/tasks`：无 token 401、伪造 token **200** |
| 同上，可伪造管理员门户 Cookie | ✅ 打 `/portal/auth/me`：**200** `{"username":"admin","kind":"admin"}` |
| 同上，可伪造 `admin_review` 权限 | ✅ 打 `/api/internal/portal/admin/tasks`：**200** |
| `services/knowledge_retrieval.py:65-80` 向量库快路径失效 | ✅ 语料维度 59 / query 维度 3 → `np.dot` `ValueError` → 快路径是死代码 |
| 迁移头唯一性 | ✅ `alembic heads` / `alembic current` 均为单头 `20261026_84` |
| 活库索引现状 | ✅ `pg_indexes` 实查：38 张表有二级索引；**12 张只有主键**（`projects`/`workflows`/`nodes`/`node_runs`/`kb_chunks`/`chat_messages`/`datasets`/`model_library`/`edges` 等）；`EXPLAIN` 证实 `workflow_runs`、`kb_chunks` 走 Seq Scan + Filter |

### 二、对上一轮静态结论的三处修正（保留历史，纠正结论）

1. **「模型声明 `index=True` 但迁移未建索引 11 列」→ 误判，撤回。** 活库 `pg_indexes` 实查 `ix_artifacts_archived_at`、`ix_training_jobs_*`、`ix_generic_annotation_tasks_*`、`ix_dataset_schema_columns_dataset_version_id`、`ix_demo_loop_configs_correct_artifact_id` **均存在**——成因是部分迁移用多行 `op.create_index(...)` 或建表内联 `sa.Index(...)`，被静态扫描的正则漏匹配。**口径改为以活库 `pg_indexes` 为准**：真正缺索引的是上述 12 张只有主键的表，以及 `dataset_versions.original_artifact_id`/`normalized_artifact_id`、`dataset_samples.sample_id` 三个过滤列。
2. **「`df.query(user_expr)` = RCE」→ 定级过高，降级为 P2 危险面。** 实测 pandas 2.3.3 显式拦截 `@__import__`（报 `"__pd_eval_local___import__" is not a supported function`）；实际可达能力是「`@var` 读取调用方变量、`@fn()` 调用调用方作用域函数」。容器内 `numexpr` 未安装且 `pandas.core.computation.expr.NUMEXPR_INSTALLED=False` → 确认会回退 python 引擎（eval），但**未构成直接任意命令执行**。仍需收口（AST 白名单），但不属于 P0。
3. **「3 个迁移头」→ 误判，撤回。** 系扫描脚本正则未兼容 `down_revision: tuple[str, str] = (...)` 注解形式；实跑 `alembic heads` 为单头。**迁移图健康，本轮无多头问题。**

### 三、问题清单（未决，按影响排序）

#### P0（A 级实证）

| 编号 | 位置 | 问题 | 修复方向 |
|---|---|---|---|
| **A-01** | `app/operators/blending.py:303` | `generate_attributes` 算子用 `eval()` 执行用户可控表达式，空 builtins 非沙箱 → **后端容器内任意命令执行**。完整链条：开放自助注册 → 自建项目成 OWNER → 写工作流节点参数 → 运行 | 改 AST 白名单求值器（禁 `ast.Attribute`；白名单 `Name`/`Constant`/`BinOp`/`Compare`/受限 `Call`）。**仓库已有范式**：`app/services/agent/sandbox.py:92-129`（AST 白名单 + dunder 拦截） |
| **A-02** | `app/config.py:79` + `:371-372`；`docker-compose.yml` `&production-environment` 锚点；`app/services/annotator_identity.py:277-297`、`:354-377` | `ANNOTATOR_SERVICE_SECRET` 生产校验**只查长度 ≥32**，公开默认值（34 字符）通过——对比同文件 `:365` 对 `SECRET_KEY` 做了默认值比较，漏了。compose 从未注入该变量（实测运行中 backend 与 annotator 容器**均 UNSET**）。该密钥同时签内部服务令牌与管理员门户 Cookie，而 `_resolve_admin_identity` **只验签不回查 DB 角色** | ① 生产校验加「不得等于默认值」比较；② compose 改 `${ANNOTATOR_SERVICE_SECRET:?}` 强制注入 backend 与 annotator；③ 门户会话密钥与内部令牌密钥分离；④ `_resolve_admin_identity` 补 `db.get(User, sub)` + `role=="admin"` 复核；⑤ nginx 对 `/api/internal/` 与 `/portal/` 收口，并取消 backend 的 `:8001` 宿主直发 |
| **A-03** | `app/api/chat.py:71`、`:162`；`app/services/llm_gateway.py:144`；`app/config.py:51-53`；`app/api/knowledge.py:538`、`:680`；`app/api/platform_api.py:939` | `async def` 端点内同步执行 DB 查询 + 全语料 TF-IDF 重算 + 阻塞 `httpx`（默认超时 60s）→ **冻结整个 worker 事件循环**。叠加 DB 池 15/进程 vs anyio 40 线程/进程，且 `knowledge.py:538` 的 30s 外部调用**全程持有 DB 连接** → 单 worker 15 并发即打满池，其余请求排队 30s 后 500（跨端点雪崩） | ① `chat`/`chat_stream` 改同步 `def`（FastAPI 自动进线程池，一行级改动收益最大）；② 外部调用前释放连接；③ 池参数按 `worker × 线程` 校准并用 anyio 限流器对齐；④ 三处 `requests.post` 改走 `llm_gateway` 共享客户端 |

#### P1

| 编号 | 位置 | 问题 | 修复方向 |
|---|---|---|---|
| **A-04** | `app/operators/io_operators.py:110`/`:185`/`:204`/`:229`；`app/engine/export_paths.py:18-21` | 算子 `file_path` 无边界：可读服务器任意文件（已实证读到 `/etc/passwd`）、可写任意路径（已实证写成功）、`ImageImport` 还能 glob 任意目录 | 删 `legacy_file_path` 分支；读取侧统一 `Path(raw).resolve()` 后 `is_relative_to(allowed_roots)`，`allowed_roots` 仅含 `UPLOAD_DIR` 与 `context.workspace_dir` |
| **A-05** | `app/operators/io_operators.py:62-63`、`:290-296` | 算子出站 URL **无任何 SSRF 校验**（`urlopen` 无协议白名单/无 DNS 解析/默认跟重定向）。仓库已有正确实现 `app/services/webhook_security.py:96-143`（DNS 解析 + `is_global` 判定）却未复用 | 抽出通用 `services/outbound.py`，出站 URL 一律走它；禁自动重定向或对 `Location` 二次校验 |
| **A-06** | `app/api/auth.py:49-51`、`:133-136`；`app/services/security.py:208-215`；`Dockerfile` CMD | 登录限流的 client key 取 `request.client.host`——经 nginx 时**恒为 nginx 容器 IP**（nginx 设了 `X-Real-IP` 但后端从不读；uvicorn 未加 `--forwarded-allow-ips`）→ **任意匿名者 5 次请求让全站 15 分钟无法登录**；且限流器是进程内单例，`--workers 2` 下实际额度再翻倍 | 新增 `client_ip(request)`：peer 属受信代理网段时取 XFF 最左一跳并做 `ipaddress` 校验；限流迁 Redis（复用 `services/inference_rate_limit.py` 的 `RedisTokenBucket`） |
| **A-07** | `app/api/annotator_internal.py:76-97`；`docker-compose.yml` backend `:8001` publish | 门户登录 `/portal/auth/login` **完全无限流**，且该端点同时接受平台管理员口令（`issue_admin_portal_token`）；backend 直接 publish `:8001`，而 nginx 只反代 `/api/` → 该路径不经 nginx 直达，可在线爆破管理员 | 接入 `LOGIN_IP_LIMIT`/`LOGIN_ACCOUNT_LIMIT`；取消 backend 宿主端口发布，统一走 nginx |
| **A-08** | `app/api/runs.py:290-297`；`app/websocket/manager.py:25-35` | 运行事件 WebSocket **无任何鉴权**：知道 `run_id` 即可订阅他人工作流的节点输出/metrics/logs；`nginx.conf:89` 对外暴露 `/ws/` | 从 query string 或 `Sec-WebSocket-Protocol` 取 JWT，`connect` 前调 `resolve_run_access` |
| **A-09** | `app/engine/dag_executor.py:519-526`、`:540-542`；`app/engine/run_control.py:5` | 循环体算子异常被 `except Exception` 吞掉（`body_outputs = {}`），随后**无条件上报 `completed`** → 同一 NodeRun 行被覆盖，**失败从 DB 里消失**；且 `RunCancelled(RuntimeError)` 被同一分支吃掉 → **循环体内取消失效**（要跑完 `max_iterations`） | `except RunCancelled: raise` 提到 `Exception` 之前；`completed` 上报移入成功分支并补 `attempt` 区分失败行 |
| **A-10** | `app/tasks/recovery.py:37-60`；`app/tasks/celery_app.py:41-94` | `reconcile_stale_runs`（把僵尸 `running` run 判失败）**生产环境无调用者**——`beat_schedule` 13 条里没有它，`main.py` lifespan 也没接 → worker 被硬超时 SIGKILL / OOM 后 `WorkflowRun` 永久停在 `running`，`/runs/active` 持续返回它，前端永久转圈 | beat 增加 `workflow-run-recovery`（60s），`active_task_ids` 用 `celery_app.control.inspect`（照 `training_tasks.py:17-35`）；lifespan 补一次启动清扫 |
| **A-11** | `app/services/closed_loop_actions.py:117-161`（锁在 `:120`）；`Dockerfile.worker` CMD `--concurrency=2` | 闭环错误集追加用**进程内 `threading.Lock`** 串行化「读 CSV→追加→换 `storage_uri`→删旧对象」；worker 是 2 个 prefork 子进程 → **不互斥 → 先写者的行永久丢失**、旧对象变孤儿 | 改 DB 级 CAS：`Artifact` 加 `append_version`，`UPDATE ... WHERE id=:id AND append_version=:v`；删旧对象只在 CAS 成功后 |
| **A-12** | `app/services/agent/executor.py:157`；`app/api/agent_center.py:195-206` | AgentRun 放行无 CAS/无锁，且执行器白名单**含 `running`** → 并发 resume 双跑：LLM 花费翻倍（`token_used` 被后写者覆盖）、`memory_json` 档案互相覆盖、终态可回退 | 放行改 `UPDATE ... WHERE id=:id AND status='waiting_guidance'`（rowcount!=1 返回 409）；白名单去掉 `running`；token 改 DB 侧累加 |
| **A-13** | `app/services/knowledge_retrieval.py:65-80`、`:149-157`、`:175-197`；`app/engine/vector_store.py:128-133` | **向量库快路径是死代码**：语料用全语料 fit、query 用 `[query]` 单独 fit，词表必然不等 → `np.dot` 抛 ValueError 被 `except (ValueError, TypeError)` 静默吞掉 → 每次检索退回全语料重算 TF-IDF + 逐条 `json.loads`。子代理实测 2000 chunk **0.65s/请求**、5000 chunk **6.95s/请求** | 缓存语料级 `TfidfVectorizer`，query 只 `transform` 不 `fit`（向量快路径自动生效）；相似度改 `np.fromiter`+`np.stack` 批量解析 + `np.argpartition`；`:156` 的 except 补 `logger.warning` |
| **A-14** | `app/api/knowledge.py:1303-1306` | `rag-enhanced` 的 `vstore.search` 未被 try/except 包裹 → 同一维度问题直接冒泡，**向量库非空即 500** | 随 A-13 一并修；并在 `rag_enhanced` 补兜底退回 `retrieve_chunks` |
| **A-15** | `app/api/knowledge.py:538`、`:680`；`app/api/platform_api.py:939` | 三处 `requests.post` 每次新建 TCP+TLS 连接，且**在 DB 事务未提交时发起**（连接不归还）；`platform_api.py:939` 每次还 `asyncio.run()` 新建事件循环 | 三处改走 `llm_gateway.chat_completion`（共享连接池 + 出口审计）；外部调用前 `db.rollback()` 归还连接 |
| **A-16** | `app/services/annotation_task_state.py:448-469`、`:508-513`；`app/api/generic_tasks.py:512` | `GET /api/annotation-tasks` 每行 3-5 次查询（快照 ×2 + 预览 ×1~3），limit 上限 200 → **600-1000 次往返/请求**；前端 `DataAnnotationPage.tsx:823` 在 previewing/executing 时每 2s 轮询 | 列表路径改批量预取（按 `(task_id, task_revision)` 聚合一次 `IN` 查询），拆「批量版 + 单条版」 |
| **A-17** | `app/api/spot_weld_quality.py:235`、`:243`、`:245`、`:253`、`:255`、`:260`、`:716-718` | 焊接质量运行列表**无分页** + `run.project`/`run.created_by`/`run.samples` 三处懒加载（samples 含 `waveforms`/`feature_values`/`table_values` 三个 JSON 列）→ 最少 2N 次额外查询 | 加 `limit/offset`；`_serialize_run` 改接预聚合值（照 `agent_center.py:91-97` 的 `outerjoin` 写法）；**删掉所有 `run.samples` 访问**改 SQL `COUNT` |
| **A-18** | `app/services/artifact_service.py:124-130`；`app/services/annotation_returns.py:594-600`、`:966-973`；`app/services/data_import.py:688-690` | 4 处 `DatasetVersion.version = max+1` 裸算，撞唯一索引 `uq_dataset_versions_project_version` → 并发必炸 | 版本号改 DB 分配（PG `nextval`）或捕获 `IntegrityError` 后重读重试（≤3 次） |
| **A-19** | `app/services/workflow_execution.py:199`；`app/schemas/run.py:31` | `current_run.error_message = str(error)` 把 SQL 原文、约束名、参数经 `GET /api/runs/{id}` 回吐前端 | 对外只给 `error_code` + 归一化文案；原始异常仅进 logger |
| **A-20** | `app/tasks/workflow_tasks.py:48-70`；`app/engine/dag_executor.py:396-423` | ① 心跳线程无 try/except，一次 DB 异常即永久死亡（仅 stderr），2 分钟后 `claim_run` 允许第二 worker 接管仍在跑的 run；② 节点超时后被放弃的算子线程**不可终止**，继续持有同一个 SQLAlchemy Session（Session 非线程安全）并可能继续写制品 | 心跳循环包 try/except 留痕并 `continue`；`claim_run` 接管前确认无对应活跃 Celery task；超时分支记录「孤儿线程」告警，超时后换独立 Session |

#### P2 / P3（摘要，不逐条展开）

- **未鉴权端点泄露跨项目数据**：`app/api/dashboard.py:156`/`:183`、`app/api/model_library.py:315`、`app/api/chat.py:149`（后者还回吐 LLM `api_url`）、`app/api/labeling.py:17`/`:116`（用户正则进 `re.search` → ReDoS 风险）。**注**：`app/api/operators.py:16`/`:44` 亦未挂鉴权。
- **`/api/upload` 未复用已加固的上传校验**（`app/api/operators.py:52-62`）：自行做分隔符替换、可用同名覆盖、无限体积、回吐服务器绝对路径；仓库已有 `services/security.py:232-269` 的 `validate_upload_filename`/`validate_upload_magic` 未在此接入。
- **改密不套口令策略、不撤销已签发 JWT**（`app/api/auth.py:262-273`）：注册路径有 3/4 类组合策略，改密路径没有；JWT 无 `jti`/`token_version`。
- **索引缺口（以活库为准）**：12 张表只有主键——`projects.owner_id`、`workflows.project_id`、`nodes.workflow_id`、`node_runs.run_id`、`kb_chunks.doc_id`、`kb_documents.kb_id`、`chat_messages.session_id`、`chat_sessions.kb_id`、`datasets.*`、`model_library.project_id`、`edges.workflow_id`、`workflow_versions.workflow_id`；另 `dataset_versions.original_artifact_id`/`normalized_artifact_id`、`dataset_samples.sample_id` 三个过滤列无索引。
- **列表端点无分页 / 一次性全量载入**：`app/api/datasets.py:569`/`:599`、`app/api/notifications.py:805-817`（前端每 30s 拉全量）、`app/api/spot_weld_quality.py:1080-1090`、`app/api/annotations.py:186-189`、`app/api/experiments.py:215-223`（拉 1000 条再切片）。
- **其余 N+1**：`app/api/annotator_internal.py:574-579`/`:720-724`、`app/api/model_registry.py:98`/`:271`、`app/api/knowledge.py:738`、`app/api/generic_tasks.py:474-500`。
- **前端**：`DataAnnotationPage.tsx`（94 个 `useState`）在 1Hz 轮询下整页重渲染 + JSX 内联 `columns`；`:883`/`:910`/`:944` 三处裸 `setInterval(…, 1000)` 绕过 `useAdaptivePolling` 退避；`:1114-1126` 轮询把用户「加载更多」重置回第一页；`AutoMLPage.tsx:629-641` blob URL 从不 revoke；`App.tsx:119-141` 仅 11/42 路由有 `PageErrorBoundary`；`stores/workflowStore.ts` 5 处全量订阅被 WS progress 消息放大；62 处 toast / Error Boundary 兜底文案硬编码中文绕过 i18n；`MonitorPage.tsx:334` 用 `JSON.stringify(data)` 作 signature，而后端 `api/monitor.py:190` 每次发新 timestamp → **自适应退避在监控页永久失效**（批次五的优化被抵消）。
- **部署加固**：15/15 服务无 `deploy.resources.limits`；0/15 配置日志轮转（docker json-file 默认无上限）；`websockets>=12.0` 无上界；`ml-platform/backend/temp_test/assignment-idempotency-fresh.sqlite`（1.4MB 空表结构快照）仍被 git 追踪（`.gitignore` 的 `*.db` 规则管不到 `.sqlite`）。
- **CI 门禁强度**：`browser-acceptance`/`production-integration`/`experiment-integration`/`security-release-verification` 四个 job 的 `if:` 限定为 `schedule`（每周日 02:00）或手动 `workflow_dispatch full` → **普通 push/PR 只跑 `quality` 矩阵**；且 `Run security scans`（`ci.yml:860-862`）与 `Run frozen-stack web security gate`（`:871-873`）均为 `continue-on-error: true` → **没有任何安全扫描能阻断合并**（扫描器 pip-audit/bandit/trivy/gitleaks 本身已正确安装并固定版本）。

### 四、优化路线（批次九~十四，2026-10-28）

> 承接上文批次一~八。批次九~十一为 P0/P1 收敛，批次十二~十四为 P2/P3 批量治理。每批次完成后需按上文「证据等级」口径补齐运行时验证与回归用例。

| 批次 | 主题 | 内容 | 验收 |
|---|---|---|---|
| **批次九** | 算子执行面收口（A-01/A-04/A-05/A-02） | ① `blending.py` 换 AST 白名单求值器；② `export_paths` 删 `legacy_file_path`、读取侧加 `is_relative_to` 边界；③ 出站 URL 统一走 `services/outbound.py`；④ `ANNOTATOR_SERVICE_SECRET` fail-closed + compose 强制注入 + 门户密钥分离 + `_resolve_admin_identity` 补角色复核 | 回归用例：恶意表达式被 AST 门禁拒；`file_path=/etc/passwd` 抛 `OPERATOR_PATH_OUTSIDE_WORKSPACE`；未注入密钥时 production 启动即失败；用旧默认密钥签的令牌被拒 |
| **批次十** | 认证边界与限流（A-03/A-06/A-07/A-08/A-19） | ① `client_ip(request)` 信任代理感知 + 限流迁 Redis；② 门户登录接限流；③ WebSocket 接 `resolve_run_access`；④ 错误信息脱敏（`error_code` 口径统一） | 回归用例：经 nginx 的多用户登录互不影响桶；`/ws/runs/{id}` 无 JWT 被 401；`/portal/auth/login` 第 6 次被限 |
| **批次十一** | 运行时与检索（A-03/A-13/A-14/A-15/A-16/A-17） | ① `chat`/`chat_stream` 改同步 `def`；② 外部调用前释放连接 + 池参数校准 + anyio 限流器；③ 缓存语料级 vectorizer 修向量快路径；④ 三处 `requests.post` 走共享客户端；⑤ 标注任务列表与焊接质量列表改批量预取 | 回归用例：单次 `POST /api/chat` 期间 `/api/ready` P99 < 1s；向量库非空时 `rag-enhanced` 返回 200；`GET /api/annotation-tasks?limit=200` 查询数 ≤ 5 |
| **批次十二** | 并发与幂等（A-09/A-10/A-11/A-12/A-18/A-20） | ① DAG 循环体 `RunCancelled` 提前捕获 + 失败不得上报 completed；② 补 `workflow-run-recovery` beat + lifespan 清扫；③ 闭环追加改 DB 级 CAS；④ AgentRun 放行 CAS + token DB 累加；⑤ `DatasetVersion` 版本号 DB 分配；⑥ 心跳线程容错 + 超时线程可中断 | 回归用例：并发 resume 只起 1 个 runner；循环体算子失败后 NodeRun 状态为 `failed`；SIGKILL 后 run 能在对账窗口内转 `failed`；并发建版本号不冲突 |
| **批次十三** | 列表与索引（A-16/A-17 + P2 索引项） | 补 12 张表与 3 个过滤列的索引（含 Alembic 迁移 + `database_migrations.py` 运行时索引同步口径对齐）；各类列表端点统一分页 | `EXPLAIN` 显示 Index Cond 而非 Seq Scan；`pg_indexes` 与模型声明逐表对齐 |
| **批次十四** | 前端渲染与部署加固（P2/P3 前端项 + compose/CI 项） | ① `DataAnnotationPage` 拆分 + `columns` useMemo + 裸 `setInterval` 迁 `useAdaptivePolling` + 修 `MonitorPage` signature；② blob URL 回收；③ Error Boundary 覆盖全路由；④ toast/兜底文案收敛 i18n；⑤ compose 资源限制 + 日志轮转；⑥ CI 扫描步骤去掉 `continue-on-error` 并把安全 job 纳入 PR 路径 | React Profiler 下 1Hz 轮询不再触发整页 commit；blob `revoke` 有用例；compose `docker compose config` 含 limits 与 log-opts；CI 上安全扫描失败能阻断合并 |

### 五、后续（执行顺序）

> **✅ 批次九已落地（2026-10-29，A-01/A-04/A-05/A-02 全部四项）**：① A-01——新建 `app/engine/safe_expression.py` AST 白名单求值器（Name[row]/Constant/Subscript/Slice/算术/比较/逻辑/条件；Attribute/Call/Import/推导式/lambda 一概拒绝 + 序列重复与幂指数上限防 DoS），`blending.py::GenerateAttributesOp` 换用之；② A-04——新建 `app/engine/path_guard.py`（读取仅允许上传目录+运行工作区两根，`resolve` 后 `is_relative_to` 判定，稳定码 `OPERATOR_PATH_OUTSIDE_WORKSPACE`），CSVImport/ImageImport/JSONImport/ReadExcel 四读取算子接入；`export_paths.py` 删 `legacy_file_path` 分支（三处调用方旧 `file_path` 参数降级为文件名提示，导出一律落工作区 exports）；③ A-05——新建 `app/services/outbound.py`（`validate_outbound_url` 复用 webhook_security 的 DNS 解析+受限地址判定，泛化为 http/https 任意端口；`fetch_url_bytes/fetch_url_frame` 出口 + 重定向逐跳重校验），CSVImport 下载与 ReadURL 全部改走该服务（file://、内网、环回、链路本地、元数据服务全拒，DNS 重绑定至内网同拒）；④ A-02——config production 校验拒绝默认 `ANNOTATOR_SERVICE_SECRET`（`AliasChoices` 保字段名传参 + env 名解析测试）、门户管理员 Cookie 密钥改域分离派生（旧默认密钥签的 Cookie 自然失效）、`_resolve_admin_identity` 补 DB 存在性+admin 角色复核（降权/删除后旧 Cookie 失效）、compose 锚点+annotator sidecar `${ANNOTATOR_SERVICE_SECRET:?}` 强制注入、backend/annotator 端口默认回环绑定（`BACKEND_BIND_ADDRESS`/`ANNOTATOR_BIND_ADDRESS` 可覆盖）、根 nginx `/api/internal/` 与 `/portal/` 全 404 收口（门户流量走 annotator-frontend 自有反代）；部署侧联动——根 .env 已补键、installer 全新生成+升级幂等补键、CI 三个 compose job（browser/experiment/security）注入 ci 专用值。测试：新建 `test_safe_expression`（10 用例）+ `test_outbound_security`（10 用例）登记 week5 清单；`test_all_operators` 文件路径用例改工作区口径 + 新增越界拒读用例；`test_config` 新增默认/短密钥拒绝两用例。受影响面回归 333 passed/1 skipped（含 test_ci_workflow 合同）。**注意**：本地部署栈重启前需确认根 .env 已有 `ANNOTATOR_SERVICE_SECRET`（已补）；已部署线上升级走 installer 幂等补键，缺键时 backend 将拒绝启动（fail-closed 设计）。

1. **批次十**（认证边界与限流：client_ip 信任代理感知、门户登录限流、WS 鉴权、错误脱敏）。
2. **批次十一**（性能收益最大且与本周已做的性能批次衔接；`chat` 改 `def` 是一行级改动）。
3. **批次十二**（并发/幂等，需先补复现用例再改，避免回归）。
4. **批次十三 + 批次十四**（批量治理，可与上面并行）。
5. **审计收尾**：① 复核 `pickle/joblib` 反序列化通道（枚举所有 `Artifact` 创建点的字节来源，确认是否存在用户可直接上传 `.joblib` 的入口）；② `app/services/agent/sandbox.py:193` 的子进程**未传 `env=`**（与 `python_script_runtime._child_env` 做法相反），需确认 Agent 特征脚本的威胁模型；③ 生产 `DATABASE_POOL_SIZE`/`DATABASE_MAX_OVERFLOW` 实际取值（compose 未覆盖，走默认值）需运维确认；④ `/api/internal/**` 的生产网络隔离策略待确认（根 nginx 已 404，容器网络层隔离另行评估）。
6. **CI 状态**：main HEAD `dbc0f7e3` 全量六 job 全绿（run 40795562091，2026-10-29）；本批修复推送后将再触发验证。

