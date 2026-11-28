# 来料检验与 SCAR（质量管理 · 质量体系）

来料检验（IQC）与供应商整改请求（SCAR）的台账与闭环。

## 数量约束

检验数 ≤ 来料数、不良数 ≤ 检验数——违反返回 IQC_COUNT_CONSTRAINT 拒绝。

## SCAR 闭环

- 检验**不合格自动生成 SCAR**（一检验一 SCAR，唯一约束）；
- SCAR 可登记**原因（cause）、纠正措施（correction）、验证（verification）**；
- **关闭门禁**：纠正措施与验证都已登记方可关闭（QMS_SCAR_CLOSE_INCOMPLETE）；重复关闭被拒（QMS_SCAR_ALREADY_CLOSED）；
- **停用供应商**：停用后新来料被拒（SUPPLIER_DISABLED）。

台账三张：供应商、检验记录、SCAR（SCAR 页面为只读台账，处理走「检验记录」行的 SCAR 关联）。
