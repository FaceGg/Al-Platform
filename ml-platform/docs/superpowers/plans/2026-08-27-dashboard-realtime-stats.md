# 工作台实时模型统计实施计划

1. 扩展 dashboard API 测试，建立 TrainingJob、ModelVersion、InferenceDeployment 和 PlatformAPI 的真实数据场景。
2. 重写 `/api/dashboard/stats` 的模型统计，按可访问项目过滤并生成互斥的训练中、已完成、已发布数量。
3. 扩展工作台刷新测试，增加 focus 和 visibilitychange 的即时重新请求。
4. 在 AutoML、普通训练及模型发布相关成功操作后广播 `platform:dashboard-stats-changed`。
5. 为公共删除确认框增加固定窄宽和移动端最大宽度，并补组件测试。
6. 执行后端专项测试、前端聚焦测试、生产构建和差异检查。
7. 将结果、未完成项和可复用经验追加到项目计划及全局开发经验。
