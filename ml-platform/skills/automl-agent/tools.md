# 平台确定性工具清单（tools.md v1）

Agent Runner 按 tools.md 调平台工具；LLM 不直接执行任何工具，只消费其输出。

| 工具 | 阶段 | 输入 → 输出 | 约束 |
|---|---|---|---|
| `profile_data` | S1 前置 | DataFrame + target → 列画像/目标分布/互信息 Top-K/高相关对/时间列 | 行样例默认不出域（17.1）；开启后 sensitive 列掩码 |
| `sandbox_run` | S2 | FeatureScript + 抽样帧 → 输出帧或结构化报错 | AST 白名单先于执行（17.2）；≤180s；≤5000 行 |
| `check_contract` | S2 | 输入帧 + 输出帧 + 泄漏列 → 违规字符串列表 | 行数/空列/常量列/泄漏/零方差 |
| `train_automl`（P3 绑定现有引擎） | S3 | 特征帧 + y + 配置提示 → Top-K 指标 + feature_importance | 数值全部来自平台 |
| `holdout_evaluate`（P3） | S4 | 模型 + 留出集 → 最终指标 | 测试集只在 S4 出现一次 |
| `evaluate_hard_gates` | S4 | 指标 + 门禁 → GateReport(passed, failures) | 一票否决；评审前执行 |
| `persist_recipe`（P3） | 验收后 | 全链路产物 → Recipe 版本 | 随后 S5 服务化 |
| `query_kb` / `search_recipes`（P3/P6） | S1 前置 | 列语义 → 知识库片段 / 相近配方 | KBBinding 配额内；引用可追溯 |

## 调用约定

- 工具输出一律为结构化 JSON/DataFrame，直接进入引述块；
- 报错回喂原样引用（含栈回溯末 3 行/契约字段名），不转述不省略；
- token 计量按次累计，超 `token_budget` 即熔断（AGENT_TOKEN_BUDGET_EXCEEDED）。
