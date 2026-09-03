# 通用化迁移基线清单

**状态：** planned，Task 1 交付物。本文档用于记录全项目去行业化盘点结果，不表示迁移已经完成。

## 目的

盘点生产后端、前端、数据库、worker、制品导出、路由、菜单、国际化和测试中的行业专用引用，定义迁移边界、兼容期限、数据转换和验证证据。

## 盘点范围

- 后端 API、service、model、schema、task 和数据库迁移。
- 前端路由、页面、API client、状态映射、菜单和 i18n。
- 数据集、标签、任务、模型、制品和导出的来源链。
- 旧 URL、旧字段、旧模型包、worker 分发和测试周次台账。

## 记录格式

| 引用位置 | 行业专用内容 | 通用替代 | 迁移策略 | 验证证据 | 状态 |
|---|---|---|---|---|---|
| 待 Task 1 扫描 | 待确认 | 待确认 | 迁移/弃用/重定向 | 待生成 | planned |

## Task 1 初始盘点（2026-09-03）

| 引用位置 | 行业专用内容 | 通用替代 | 迁移策略 | 验证证据 | 状态 |
|---|---|---|---|---|---|
| `backend/app/api/spot_weld_quality.py` `/api/projects/{project_id}/spot-weld/runs` | 点焊质量运行创建写入口 | `/api/annotation-tasks`、`/api/automl-tasks` | 新写请求结构化返回 `410 GENERIC_API_REQUIRED`；旧读取与历史服务保留 | `tests/test_genericization_contract.py::test_legacy_spot_weld_write_is_closed` | in_progress |
| `backend/app/models/spot_weld_quality.py` 运行、样本、标签修订/快照模型 | 行业化持久化表和字段 | `GenericAnnotationTask` 的 UUID 引用与 `label_snapshot` | 只读适配器复制，不删除原行；后续 Task 2/4 建立正式数据版本和 schema；当前保留 source IDs/count/checksum | `migrate_legacy_quality_run` focused contract | in_progress |
| `backend/app/services/spot_weld_features.py` `FEATURE_SCHEMA` 等 | 固定行业特征构建 | 通用输入合同（Task 2） | 仅允许旧服务作为迁移/兼容边界，新通用入口不导入该模块 | Task 1 source scan（待完整依赖环境） | planned |
| `ml-platform/frontend/src` 点焊页面和 API client | 行业化导航与请求命名 | 通用标注任务页面/API（Task 12） | 保留历史页面，后续替换生产导航和 i18n | Task 12 UI contract | planned |

本次盘点只建立迁移边界和可审计适配器；正式 `DatasetVersion`、`LabelSchema`、revision 表和输入合同属于后续 Task 2/4，不在 Task 1 提前创建。

Task 1 remaining（未完成）：`ml-platform/frontend/src/App.tsx`、`pages/AnnotationPage.tsx`、`pages/DataAnnotationPage.tsx`、`api/spotWeldQuality.ts` 和 `i18n/index.tsx` 的生产导航/API 文案仍保留历史兼容入口；`spot_weld_quality` service/features/task/model 仍作为只读迁移适配边界，待后续任务完成全面替换和扫描收口。

拆分裁定：前端生产导航和 API client 文案属于 Task 12 的主平台/标注员门户交付；Task 1 仅建立后端通用边界、旧写入口关闭、迁移适配器和禁止新代码依赖行业 feature builder 的门禁。上述前端文件与旧服务的全面替换不在本轮验收范围，必须在 Task 12 通过对应 UI/E2E 和 source-scan 证据后才能关闭。

## 迁移门禁

1. 新业务代码不得依赖固定行业字段、特征 schema、行业标签或行业专用路由。
2. 旧写入入口必须返回结构化弃用响应或明确重定向。
3. 旧数据只允许在校验行数、sample_id 和校验和后写入新通用版本，不删除原始记录。
4. 扫描结果、迁移结果和回归测试必须绑定同一当前 Git SHA。
