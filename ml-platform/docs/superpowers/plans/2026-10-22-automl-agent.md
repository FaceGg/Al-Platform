# AutoML Agent 智能体实施计划（P1–P6）

> For agentic workers: **本计划无未决决策门**——技术方案 v0.9（2026-10-22 全面评审修订版）已把
> 全部默认值定稿（deprecated 保留 14 天、RSI 回归集 ≤10、shadow 一周期、token 预算任务级可配），
> 可自 Task A1.1 起执行。2026-10-22 用户指示：Week 17–20 让位待定，由本计划主导后续开发。

**Goal:** 交付大模型驱动的自动建模智能体——LLM 网关、四步迭代（S1 分析/S2 自我纠错/S3 AutoML/S4 双门）、
配方固化、S5 服务化（draft 批准语义）、跨任务经验与有界 RSI、向导、优化总结报告、统一知识中心、对话工具白名单。

**Architecture:** LLMProfile 网关统一全部 LLM 出口（chat/knowledge/orchestration/agent）→ Agent Runner
（薄编排器）读 `ml-platform/skills/automl-agent/` 驱动四步循环 → 配方 Recipe 版本化 → S5 复用现有
注册-部署-闭环-编排链路（编排 `load_model` 改绑部署引用）；经验 ExperienceEntry 为知识中心结构化真源。

**Tech Stack:** 现有 FastAPI/SQLAlchemy/React/antd 栈零新增基础设施；S2 沙箱用受限子进程（AST 白名单
用标准库 `ast`，无新依赖）；契约校验用 pydantic（已有）。

**Spec:** [技术方案 v0.9](../../技术方案-大模型驱动自动建模流水线.md)（十七章，冲突以其为准）、
[前端预览](../../design/平台改版前端预览.html)（UI 规格）、DEVELOPMENT_PLAN.md §2 总览。

## Global Constraints

- 技术方案 v0.9 为唯一设计依据；实现与其冲突时先改文档再改码。Week 17–20 与 Label Studio 的
  既有代码与文档不动（其状态让位，不撤销）。
- **迁移红线**：每阶段一个迁移，新 head 常量同步 **5 处**（`tests/test_database_production.py`、
  `tests/test_inference_production_stack.py`、`tools/upgrade_fixture.py`、
  `tools/acceptance/run_upgrade_fixture.sh`、`tools/evidence_manifest.py`）；布尔默认 false；
  同批迁移列 nullable 一致。
- **安全红线**（十七章）：S2 脚本 AST 白名单先于沙箱执行；档案 `api_url` 仅 https、禁内网网段；
  行样例默认关闭；引述隔离封装只有 `llm_gateway.py` 一个实现点。
- **S5 红线**（12.1/12.6）：批准前三资产 draft/paused；冒烟 dry_run **零回流写入**（有测试断言）；
  项目级服务化互斥锁。
- **网关收口**（14.1）：knowledge 等接口请求级 `llm_api_url` 覆盖参数移除，运行期改端点只经档案。
- 测试登记：`tests/week_manifest.py` 新增 `PHASE_TEST_MODULES: dict[str, list[str]]`（键 `p1`–`p6`），
  `run_suite.py` 增加 `--phase` 参数（模式同 `--week`）；周键 1–17 不动（18 键保留给 Week 18 待定轨）。
- 前端每阶段跑**全量 Vitest**（本地全量必跑，不是只跑新文件）+ tsc + build；新错误码进 i18n 中英。
- Mimosa 已知误报：含 `pd.DataFrame(`/`def execute(` 的新服务文件如被扫描拦截，按注册表覆盖绕行。
- LLM 调用走真实档案做冒烟时**不得**用生产知识库/生产项目数据（行样例默认关）。

## File map

Create（按阶段；同阶段内一个迁移）：

- **P1**：`app/models/llm_profile.py`、`app/schemas/llm_profile.py`、`app/services/llm_gateway.py`、
  `app/api/llm_profiles.py`、`app/services/agent/profile_data.py`、`app/services/agent/contracts/`
  （AnalysisReport/FeatureScript/ReviewVerdict）、`app/services/agent/llm_client.py`、
  `tests/test_llm_profiles_api.py`、`tests/test_llm_gateway.py`、`tests/test_agent_profile_data.py`、
  `tests/test_agent_contracts.py`、`frontend/src/pages/LLMGatewayPage.tsx`（系统管理）+ 测试
- **P2**：`app/models/agent_run.py`、`app/services/agent/sandbox.py`、`app/services/agent/runner.py`、
  `app/services/agent/hard_gates.py`、`ml-platform/skills/automl-agent/`（SKILL.md/tools.md/contracts/）、
  `tests/test_agent_sandbox.py`、`tests/test_agent_runner.py`、`tests/test_agent_hard_gates.py`、
  前端 `AgentCenterPage`（任务列表/运行时间线）+ 测试
- **P3**：`app/models/recipe.py`、`app/models/experience_entry.py`、`app/services/agent/recipe.py`、
  `app/services/agent/experience.py`、`app/services/agent/servitize.py`、
  `tests/test_agent_recipe.py`、`tests/test_agent_experience.py`、`tests/test_agent_servitize.py`、
  前端配方库页 + 测试
- **P4**：`app/models/skill_revision.py`、`app/services/agent/skill_revision.py`、
  `tests/test_agent_skill_revision.py`
- **P5**：`app/services/agent/wizard.py`、`app/services/agent/optimization_report.py`、
  `app/models/prompt_template.py`、`tests/test_agent_wizard.py`、`tests/test_agent_optimization_report.py`、
  前端四步向导（五步含服务化预览）+ 测试
- **P6**：`app/models/kb_binding.py`、`app/services/knowledge_center.py`、`app/services/chat_tools.py`、
  `tests/test_kb_bindings.py`、`tests/test_knowledge_center.py`、`tests/test_chat_tools.py`、
  前端知识中心页（合并呈现）+ 对话工具预览卡 + 测试

Modify：

- `app/config.py`（网关/出域/token 预算设置）、`app/main.py`（路由）、`app/api/chat.py`、
  `app/api/knowledge.py`（切网关+收请求级 URL 覆盖）、`app/services/orchestration` 的
  `load_model` 算子（P3 改绑部署引用）、`app/services/closed_loop_actions.py` 与
  `demo_loop.py`（P3：dry_run 冒烟标志、任务创建 paused、服务化互斥）、
  `tests/week_manifest.py`、`run_suite.py`、`frontend/src/App.tsx`/`components/AppLayout.tsx`/`i18n`

## Task A0 状态确认——已收口（2026-10-22）

- [x] 技术方案 v0.9 定稿（19 项评审发现全部修订）；前端预览同步；DEVELOPMENT_PLAN 总览登记。
- [x] 无未决决策门：v0.9 默认值即基线；Week 17–20 让位待定（不撤销已获批范围）。

Verification: DEVELOPMENT_PLAN.md §2 总览与本文档一致；A1.1 起可执行。

## Task A1.1 套件登记与工具（P1 先行）

- [ ] `week_manifest.py` 增 `PHASE_TEST_MODULES`（p1–p6 空列表起步）+ `ALL_TEST_MODULES` 合并逻辑；
  `run_suite.py` 增 `--phase pN`（与 `--week` 同模式，--include-deprecated 语义保持）。
- [ ] RED：`--phase p1` 在空模块组上跑通且不影响 `--week` 既有输出。

## Task A1.2 LLMProfile 模型与 API（RED → 实现）

- [ ] RED（`test_llm_profiles_api.py`）：仅系统管理员可建改（非管理员 403）；api_key 只写不读
  （响应掩码）；api_url 校验（http 拒绝、`127.0.0.1`/`10.x`/`192.168.x`/`169.254.x`/localhost 拒绝）；
  连通性测试走同一校验；配置变更入审计；`deployment: cloud|private` 标记；默认档案唯一约束；
  迁移空库 upgrade/downgrade/check。
- [ ] 实现：模型（api_key 以主钥 env `LLM_MASTER_KEY` 加密存储）+ `llm_profiles.py` API + 迁移
  `20261022_75_llm_profiles.py`（head 常量 5 处同步）。
- [ ] env 迁移：启动时 `llm_api_url/key/model` 非空且无档案 → 幂等创建"内置默认档案"。

## Task A1.3 网关服务与消费方切换（RED → 实现）

- [ ] RED（`test_llm_gateway.py`）：三消费方（chat/knowledge/orchestration LLM 调用）全部经网关取
  档案；请求级 `llm_api_url` 覆盖参数移除后旧调用 422（带弃用说明）；出域审计记录
  （档案/目的/字符数，无内容本体）；档案删除前有引用则 409。
- [ ] 实现 `llm_gateway.py`（档案解析 + 调用封装 + 引述隔离工具 + 出域审计）并切换三处调用点。

## Task A1.4 profile_data 画像工具（RED → 实现）

- [ ] RED（`test_agent_profile_data.py`）：列画像（类型/缺失率/基数/分位数/常量列）、目标列
  （分布/不平衡度/标签语义）、互信息 Top-K、高相关对 >0.95、时间列识别、列名中文注解拆分
  （`ACTUAL_TORQUE(实际扭矩)` → 基础名+语义）；同输入两跑确定性；行样例默认不输出（策略开启后
  ≤20 行 + sensitive 列掩码）。
- [ ] 实现：复用 Week 17 质量 profile 的固定模板设计（该服务已获批未实现，此处按同模式起步，
  不占用其 Task 17.x 编号）。

## Task A1.5 三契约与 S1 离线验证

- [ ] RED（`test_agent_contracts.py`）：三契约 Schema 校验负例逐字段（缺 domain_hypothesis、
  focus_channels 空列名、gates 非数值等拒绝）。
- [ ] 实现 `llm_client.py`（走网关）+ S1 提示词组装（画像+目标语义+KB 检索可接 v0.9 16.3 的
  空实现占位）。
- [ ] 离线验证（不进 CI）：电焊/拧紧数据集各出一版 `AnalysisReport`，人工核对聚焦通道与预期特征
  覆盖现有 73 维/6 派生列核心；第三域公开数据集（SMT/CNC）验证域自动发现；报告存
  `temp_test/agent-p1/`。

**P1 Exit gate**：网关 CRUD/掩码/审计/URL 校验全绿；三消费方切换后既有测试全过（无行为回归）；
画像与契约测试绿；两域+第三域离线报告可核对；alembic 三态 + 前端全量三件套 + `git diff --check`。

## Task A2.1 S2 沙箱与 AST 白名单（RED → 实现）

- [ ] RED（`test_agent_sandbox.py`）：AST 拒绝矩阵——`import os/socket/subprocess/requests`、
  `open/eval/exec/__import__`、白名单外 import、非白名单库；合法脚本（pandas/numpy/math/
  statistics/scipy.stats）通过；受限子进程：限时/限内存/禁网络/禁模型；行数不变/全空列/常量列/
  含 leakage_suspects/方差 0 逐项契约违规报错可结构化回喂。
- [ ] 实现 `sandbox.py`（AST 检查器 + 受限执行器，Windows/Linux 双路径可测）。

## Task A2.2 Agent Runner 与轮内记忆（RED → 实现）

- [ ] RED（`test_agent_runner.py`）：任务状态机（running→各阶段→waiting_escalate/accepted/failed）；
  迭代 ≤3 轮、S2 ≤8 次、同类错误 ≥3 次注入 meta 提示；L1 记忆下一轮确实携带（断言提示词包含上轮
  报错-修复对）；token 预算熔断（mock 计数超限 → 暂停+升级）；任务档案记录 LLM 档案 ID+model_id；
  引述隔离（数据内容出现在引述块外 → 拒绝组装）。
- [ ] 实现 `runner.py` + `agent_run.py` 模型 + 迁移；skills 目录 v1（SKILL.md/tools.md/contracts
  从方案三章/五章落文）。

## Task A2.3 S4 双门与端到端（RED → 实现）

- [ ] RED（`test_agent_hard_gates.py`）：少数类 precision/recall/F1/AUC 阈值一票否决；Top-K 方差
  门禁；重要性 Top10 含 leakage_suspects 拒绝；LLM 不可放宽（评审 fail 只进 hints）。
- [ ] 端到端（真实 LLM 档案，离线记录）：电焊/拧紧各一次——LLM 从零写脚本收敛（记录修复轮数）；
  人为注入一轮 S4 fail 验证回环且下轮引用上轮教训；证据存 `temp_test/agent-p2/`。

**P2 Exit gate**：AST 拒绝矩阵全绿（含一个恶意/越权脚本样例）；两域端到端收敛记录在案；
`run_suite --phase p2` 绿；前端全量三件套。

## Task A3.1 配方与经验库（RED → 实现）

- [ ] RED（`test_agent_recipe.py`）：版本化（v1.2→v1.3 diff 存档、一键回滚）、lineage 串联；
  delta 复用（画像差异小直接跑 / 差异大进完整迭代，脚本 dry-run 判定）。
- [ ] RED（`test_agent_experience.py`）：条目契约校验；shadow 状态（命中记录但不注入）满一周期
  转 active；检索 `confidence ≥ 0.7 且 status=active`（边界含 0.7）；retired/superseded 过滤；
  证据链字段必填。

## Task A3.2 回流重训按配方 + 编排绑部署引用（RED → 实现）

- [ ] Modify `load_model` 算子：绑部署引用（换模自动跟随），制品仅 lineage；RED：换 deployment
  revision 后编排调用走新模型、旧制品文件不受影响。
- [ ] 按配方重训链路：配方门禁不过不换模；硬门禁失败 → 唤醒智能体重新迭代（状态衔接）。

## Task A3.3 S5 服务化（RED → 实现）

- [ ] RED（`test_agent_servitize.py`）：①–④ 产物 draft/paused 断言（模型 API 不在市场、闭环任务
  paused、编排版本 pending）；**冒烟 dry_run 零回流写入**（错误数据集计数不变——这是实测踩过的坑，
  必须有负例断言）；批准激活三资产；项目级互斥（并发两任务 S5 串行）；API 名称冲突自动后缀 v2；
  缺陷类方向从 target_semantics 推导并在预览明示。
- [ ] 实现 `servitize.py` + demo_loop/closed_loop_actions 的 paused 创建与 dry_run 标志。

**P3 Exit gate**：拧紧回流按配方自动重训换模且编排 API 跟随新部署；新抽样 delta 复用跑通；
第二个任务首轮受益于第一个任务经验（对比无经验基线记录）；`--phase p3` 绿 + 前端全量。

## Task A4.1 有界 RSI（RED → 实现）

- [ ] RED（`test_agent_skill_revision.py`）：触发去抖（同刻至多一个提案）；回归集 ≤10 配方代表
  抽样（超出按域代表+最新优先）；回归只跑 S1/S2/S4（S3 不重跑——断言无 AutoML 提交）；任一劣化
  驳回并回写经验；低风险白名单自动生效 / 中高风险与硬门禁收紧必须人工；**任何提案不得放宽**
  门禁与契约（放宽类 diff 直接拒绝）；版本化 diff 存档可回滚；运行中任务不受热改影响。
- [ ] 人为注入可泛化教训（"索引列默认剔除"）走通 ≤3 任务提炼进 SKILL.md 的全链路。

**P4 Exit gate**：上链全绿 + 提炼链路证据 + 回滚演示；`--phase p4` 绿。

## Task A5.1 向导 UserGuidance（RED → 实现）

- [ ] RED（`test_agent_wizard.py`）：第四契约校验；注入优先级（用户引导 > L2 > 技能默认）；
  algorithm_whitelist 限定 S3 搜索空间；metric_gates 替换默认但**低于默认时黄条警示记录审计**；
  逐步确认模式 waiting_guidance 暂停位（S1–S4 各一）；提示词模板 CRUD（用户/项目维度，不入经验库）。
- [ ] 前端四步向导（antd Steps；载入配方预填=编辑器）；第 5 步服务化发布预览卡。

## Task A5.2 OptimizationReport（RED → 实现）

- [ ] RED（`test_agent_optimization_report.py`）：what_optimized/findings/strengths/unsatisfactory
  （必带 cause+missing+suggestion）/metrics/cost（token/档案/时长/轮数——数字取自计量非 LLM）；
  每次任务结束自动生成入档案与配方版本说明。

**P5 Exit gate**：一次填完与逐步确认两模式各跑通一次；`--phase p5` 绿 + 前端全量。

## Task A6.1 统一知识中心（RED → 实现）

- [ ] RED（`test_kb_bindings.py`）：KBBinding 全字段生效（enabled/scope/projects/agent_tasks/
  chat/agent_s1/retrieval 四参/sync 三参）；系统分区不可关不可删；随时改随时生效。
- [ ] RED（`test_knowledge_center.py`）：S1 统一检索（绑定库+经验分区合并去重截断预算，注入标注
  来源）；kb_citations 引用落档（含 exp-xxxx 条目 ID）；跨域经验投影（≥门槛、幂等键=条目 ID、
  human_review 时点）；分区正文只读 + 状态操作（retire/supersede/human_note）回写真源即刻过滤。

## Task A6.2 对话 ChatTools（RED → 实现）

- [ ] RED（`test_chat_tools.py`）：白名单封闭集（未注册工具不存在于 schema）；写操作必经确认
  （未确认不执行）；执行走用户本人权限（越权 403）；删除/权限/密钥类工具不存在；每次调用入审计；
  `save_insight`（origin=human/confidence=0.75 直接 active/引述隔离提取/确认后写 L2+投影）；
  `get_api_call_example` / `query_recipe_reports` 读工具。
- [ ] 端到端：对话经确认创建一条真实闭环任务（测试项目）+ save_insight 回写经验。

**P6 Exit gate**：四库配置生效可验证；对话→任务→经验回写链路证据；`--phase p6` 绿 + 前端全量。

## 台账收口（每阶段完成后）

- 先更新 DEVELOPMENT_PLAN.md（总览行 + 该阶段记录），再归档详细证据到 `temp_test/agent-pN/`；
  阶段完成 ≠ 发布就绪——发布仍走既有 CI 六 job + 证据绑定 SHA 的总门禁。

## Explicit exclusions

- 不动 Week 17–20 与 Label Studio 的代码、方案与状态；不部署 Superset；
- 对话工具白名单不进删除/权限/密钥类；S2 沙箱与 AST 白名单不因调试方便放宽；
- 不以本文档或技术方案宣称完成；冒烟验证不写生产回流；未收口前不宣称阶段完成。
