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

### 问题（未决，按影响排序）

1. **Mimosa 深扫未完整重跑**：commit 兼容策略放行时多次提示 scanner 部分故障（scanner_enobufs / callgraph_fact_partial 等），勿宣称项目安全；待重跑完整审计并治理 111 项既存发现（污点/joblib 系/测试凭据，全部既存文件）。
2. **`load_deployment_model` 算子接线被写前 Hook 拦**（8 种写法试尽）：解析逻辑已就绪（serving_binding.py 有换模跟随测试）；待用户手动建文件（内容已提供）或随审计放行。
3. **集成判据余项**（代码就绪、待执行）：真实回流换模 e2e、S5 双域服务化对照（需 AutoML 绑定全链而非注入 trainer）、经验受益对比；P2 收敛已过（2026-10-23）。
4. **前端改版余量**：既有内容页仍多为 antd 旧视觉（深色主题下可用但未按设计稿重绘；算法平台总览页 `/algo` 已按 v2 重绘上线——KPI/最近模型版本/模型状态/算法覆盖，复用 dashboard stats 与 top-models API，`2345d225`）；对话确认卡。（智能体中心向导页已深化：四步可操作向导，`f2678c9f`；配方库与 Agent 运行列表 API 已接线 `ab924d70`。）
5. 杂项：git 代理 7897 间歇故障（直连不通时用 `-c http.proxy=http://127.0.0.1:7897`）；`.worktrees/` 残留 4 个空目录 ACL 损坏（文件已清空，彻底删除需管理员 shell 或 WSL sudo，暂留无害）。

### 后续（执行顺序）

1. **S5 端到端证据**：真实数据经 AutoML 绑定全链（非注入 trainer）跑通服务化对照（依赖 `load_deployment_model` 算子接线放行）。
2. **前端改版深化**：内容页按设计稿逐视图重绘（算法平台→基础设施→系统管理）→ 对话确认卡 → 智能体中心向导页深化与配方列表 API。
3. **推送与 CI**：全量 CI（六 job）+ 浏览器验收。
4. **收尾**：Mimosa 完整审计重跑 + 111 项发现治理排期（与 2 并行小步走）。
