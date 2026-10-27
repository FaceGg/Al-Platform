# 当前开发计划

> 更新时间：2026-10-23。当前主线：AutoML Agent 智能体方案（P1–P6 代码面完成，前端改版 v2 壳层已上线）。已完成工作的完整历史记录见 [DEVELOPMENT_PLAN_ARCHIVE.md](DEVELOPMENT_PLAN_ARCHIVE.md)（2026-10-23 归档快照，含更早的 2026-09-24 快照链接）；实施计划索引见 [plans/README](ml-platform/docs/superpowers/plans/README.md)。

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
