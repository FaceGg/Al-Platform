# 导出与离线运行时清单

**状态：** planned，Task 14 交付物。

## 导出包

- [ ] 模型、预处理、映射表、输入/输出合同和推理代码齐全。
- [ ] `manifest.json`、`checksums.json`、SPDX SBOM 和 detached signature 齐全。
- [ ] 关联自动标注修订时包含策略、聚类方法、聚类工件、簇标签映射和规则工件。
- [ ] 不包含真实数据、样本、标签、账号、凭据或私钥。
- [ ] 所有文件 SHA-256、运行时版本、依赖、seed 和合同 hash 可复核。

## 离线校验

- [ ] 支持 CSV、Excel、Parquet、JSON、XML，并校验 parse contract。
- [ ] 缺列、类型错误、非法值、sample_id 异常和输出契约错误整批拒绝。
- [ ] 失败只生成脱敏 `validation-report.json`，不保留部分输出。
- [ ] 下载需要一次性授权、审计记录和签名/校验通过。
