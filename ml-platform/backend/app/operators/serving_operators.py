# -*- coding: utf-8 -*-
"""Serving-path operators for orchestration APIs published from workflows.

`api_input` receives the single record injected by the invoke endpoint;
`load_model_artifact` binds a frozen trained-model artifact so the serving
graph never retrains per row (training stays in the training workflow).
"""
import io
import uuid

import joblib
import numpy as np

from app.engine.operator_contract import OperatorContext, OperatorResult
from app.engine.base_operator import BaseOperator, PortSpec, ParamSpec
from app.engine.registry import register_operator
from app.services.model_artifact_sealing import seal_is_valid


def _inject_feature_names(model, names: list[str]) -> str | None:
    """把训练特征列名挂到模型上，返回注入方式（None 表示该库不支持）。

    sklearn 原生模型的 ``feature_names_in_`` 可写；xgboost 的同名属性是只读
    property（实际存储在 booster.feature_names，predict 按列名校验）；lightgbm
    等库无公开写入口——注入失败返回 None，调用方降级告警而不是让加载节点崩溃。
    """
    values = np.array(names, dtype=object)
    try:
        model.feature_names_in_ = values
        return "sklearn"
    except AttributeError:
        pass
    try:
        model.get_booster().feature_names = list(names)
        return "xgboost_booster"
    except Exception:
        pass
    return None


@register_operator
class ApiInputOperator(BaseOperator):
    id = "api_input"
    name = "API Input"
    category = "closed_loop"
    description = "Record injected by the orchestration API invoke call"
    inputs = []
    outputs = [PortSpec("data", "DataTable", "Invoked Record")]
    parameters = []

    def validate(self, inputs):
        return True

    def execute(self, context: OperatorContext, inputs, params) -> OperatorResult:
        record = getattr(context, "payload", None)
        if record is None:
            raise RuntimeError(
                "API input payload is missing; this operator only runs inside "
                "an orchestration API invoke call"
            )
        rows = record if isinstance(record, list) else [record]
        if not rows:
            raise RuntimeError("API input payload is empty")
        return OperatorResult(outputs={"data": rows})


@register_operator
class LoadModelArtifactOperator(BaseOperator):
    id = "load_model_artifact"
    name = "Load Model Artifact"
    category = "closed_loop"
    description = "Load a frozen trained-model artifact for serving"
    inputs = []
    outputs = [PortSpec("model", "Model", "Loaded Model")]
    parameters = [
        ParamSpec("model_artifact_id", "str", "", "Model Artifact ID", required=True),
    ]

    def validate(self, inputs):
        return True

    @staticmethod
    def _package_feature_names(package: dict) -> list[str]:
        """从打包工件元数据提取训练特征列名（feature_schema 优先，input_contract 兜底）。"""
        schema = package.get("feature_schema")
        if (
            isinstance(schema, list) and schema
            and all(isinstance(item, dict) and item.get("name") for item in schema)
        ):
            return [str(item["name"]) for item in schema]
        contract = package.get("input_contract")
        if isinstance(contract, dict):
            columns = contract.get("input_columns") or contract.get("required_columns")
            if isinstance(columns, list) and columns:
                return [str(column) for column in columns]
        return []

    def execute(self, context: OperatorContext, inputs, params) -> OperatorResult:
        artifact_id = str(params.get("model_artifact_id") or "").strip()
        if not artifact_id:
            raise RuntimeError("model_artifact_id is required")
        if context.artifact_service is None or not context.project_id:
            raise RuntimeError("Artifact service and project context are required")
        try:
            artifact = context.artifact_service.resolve(
                artifact_id, context.project_id, expected_type="model",
            )
            with context.artifact_service.storage.open(artifact.storage_uri) as handle:
                payload = handle.read()
        except Exception as e:
            raise RuntimeError(f"Failed to load model artifact: {e}") from e
        # 非 joblib 工件（如模型注册表导出的 ONNX）拿去 joblib.load 只会抛出
        # 裸 "KeyError: 8" 之类反序列化噪声——按工件声明的格式前置拦截。
        artifact_format = str(getattr(artifact, "format", "") or "").strip().lower()
        if artifact_format and artifact_format not in ("joblib", "pkl", "pickle"):
            raise RuntimeError(
                f"模型工件是 {artifact_format.upper()} 格式，本算子仅支持 joblib 格式的模型工件"
                "（如 AutoML 任务注册的 .joblib 产物）；ONNX 模型请通过推理部署或模型 API 调用"
            )
        # 反序列化密封验签：工件必须由平台写入口创建（HMAC 标签绑定内容
        # hash）。自助上传的裸 joblib/pickle 没有有效 seal，在此拒绝——
        # 否则项目内任意成员可借编排节点触发服务端任意代码执行
        # （Mimosa 2026-11-03 "不安全反序列化"收口）
        if not seal_is_valid(
            getattr(artifact, "metadata_", None),
            str((getattr(artifact, "metadata_", None) or {}).get("sha256") or ""),
        ):
            raise RuntimeError(
                "MODEL_SEAL_INVALID: 模型工件缺少平台密封标签或标签与内容不符"
                "（仅平台训练产物可加载；请通过 AutoML/训练算子产出模型工件）"
            )
        try:
            loaded = joblib.load(io.BytesIO(payload))
        except Exception as e:
            raise RuntimeError(
                f"模型工件无法按 joblib 反序列化（格式声明: {artifact_format or '未知'}）: {e}; "
                "请确认选择的是 joblib 格式模型工件"
            ) from e
        if isinstance(loaded, dict):
            # Model-library/AutoML artifacts package the estimator inside a
            # metadata dict; unwrap it for apply_model.
            package = loaded
            for key in ("model", "estimator", "clf", "pipeline", "best_model"):
                candidate = loaded.get(key)
                if candidate is not None and hasattr(candidate, "predict"):
                    loaded = candidate
                    break
            else:
                raise RuntimeError(
                    "Model artifact is a package without a predictable estimator; "
                    "publish the deployment inference API instead"
                )
            # numpy 拟合的 estimator 没有 feature_names_in_，训练特征列名只在
            # 工件的 feature_schema/input_contract 里——按库能力注入（sklearn
            # 直写 / xgboost booster），下游评估与 apply_model
            # （predict_with_hint）才能按列名对齐，而不是把测试数据的全部列
            # 按位置喂入导致 "X has N features, expecting M"。
            if not hasattr(loaded, "feature_names_in_"):
                names = self._package_feature_names(package)
                n_features = getattr(loaded, "n_features_in_", None)
                if names and isinstance(n_features, int) and n_features == len(names):
                    injected = _inject_feature_names(loaded, names)
                    if injected is None:
                        context.logger.warning(
                            f"模型工件包含特征列名（{len(names)} 列），但 {type(loaded).__name__}"
                            " 不支持附加特征名——评估/推理将无法按列名自动对齐特征",
                        )
        if not hasattr(loaded, "predict"):
            raise RuntimeError("Model artifact does not expose a predict method")
        # Re-serialize the bare estimator so the model port carries something
        # downstream apply_model can consume directly.
        buffer = io.BytesIO()
        joblib.dump(loaded, buffer)
        return OperatorResult(outputs={"model": buffer.getvalue()})


@register_operator
class AppendErrorDatasetOperator(BaseOperator):
    id = "append_error_dataset"
    name = "Append Error Dataset"
    category = "closed_loop"
    description = "Append the branch rows to an error dataset artifact (closed loop)"
    inputs = [PortSpec("data", "DataTable", "Error Rows")]
    outputs = [PortSpec("data", "DataTable", "Appended Rows")]
    parameters = [
        ParamSpec("dataset_artifact_id", "str", "", "Error Dataset Artifact ID", required=True),
    ]

    def validate(self, inputs):
        return True

    def execute(self, context: OperatorContext, inputs, params) -> OperatorResult:
        import pandas as pd

        from app.services.closed_loop_actions import (
            append_rows_to_dataset_artifact,
            json_value,
        )
        artifact_id = str(params.get("dataset_artifact_id") or "").strip()
        if not artifact_id:
            raise RuntimeError("dataset_artifact_id is required")
        if context.artifact_service is None or not context.project_id:
            raise RuntimeError("Artifact service and project context are required")
        rows = inputs.get("data")
        if rows is None:
            rows = []
        if isinstance(rows, dict):
            rows = [rows]
        frame = rows if isinstance(rows, pd.DataFrame) else pd.DataFrame(rows)
        records = json_value(frame.to_dict(orient="records"))
        artifact = context.artifact_service.resolve(
            artifact_id, context.project_id, expected_type="dataset",
        )
        total = append_rows_to_dataset_artifact(
            context.artifact_service.db, context.artifact_service, artifact, records,
        )
        return OperatorResult(
            outputs={"data": records},
            metrics={"total_rows": float(total)},
        )


@register_operator
class NotifyAdminsOperator(BaseOperator):
    id = "notify_admins"
    name = "Notify Admins"
    category = "closed_loop"
    description = ("Send an in-app notification to the project owner and platform "
                   "admins; optional row threshold notifies once per N accumulated "
                   "error rows instead of on every reflow")
    inputs = [PortSpec("data", "DataTable", "Trigger Rows")]
    outputs = [PortSpec("data", "DataTable", "Trigger Rows")]
    parameters = [
        ParamSpec("title", "str", "", "Notification Title", required=True),
        ParamSpec("message", "str", "", "Notification Body", required=True),
        ParamSpec("severity", "select", "warning", "Severity",
                  options=["info", "warning", "critical"]),
        ParamSpec("threshold_rows", "int", 1, "Notify Every N Error Rows (1 = always)", range_min=1),
        ParamSpec("error_dataset_artifact_id", "str", "",
                  "Error Dataset Artifact ID (accumulation counter; empty = always notify)"),
    ]

    def validate(self, inputs):
        return True

    def execute(self, context: OperatorContext, inputs, params) -> OperatorResult:
        from app.services.closed_loop_actions import notify_project_admins
        rows = inputs.get("data")
        if rows is None:
            rows = []
        if isinstance(rows, dict):
            rows = [rows]
        count = len(rows)
        title = str(params.get("title") or "").strip() or "闭环流程通知"
        body = str(params.get("message") or "").strip() or f"闭环流程触发（{count} 行）"
        if context.artifact_service is None or not context.project_id:
            raise RuntimeError("Artifact service and project context are required")
        # 阈值节流：按报错数据集累计行数（上游回流已落库，row_count 含本次），
        # 每满 N 行通知一次；未配置数据集或 N=1 时保持每行通知的旧行为。
        threshold = max(1, int(params.get("threshold_rows") or 1))
        dataset_id = str(params.get("error_dataset_artifact_id") or "").strip()
        total = None
        if threshold > 1 and dataset_id:
            artifact = context.artifact_service.resolve(
                dataset_id, context.project_id, expected_type="dataset",
            )
            total = int((artifact.metadata_ or {}).get("row_count", 0))
            if total % threshold != 0:
                return OperatorResult(
                    outputs={"data": rows if isinstance(rows, list) else [rows]},
                    metrics={"notified": 0.0, "total_rows": float(total),
                             "threshold_rows": float(threshold)},
                )
            body = f"{body}（累计 {total} 行报错）"
        sent = notify_project_admins(
            context.artifact_service.db,
            context.project_id,
            title=title,
            body=body,
            severity=str(params.get("severity") or "warning"),
            event_type="closed_loop.notify",
            payload={"rows": count, "total_rows": total},
        )
        return OperatorResult(
            outputs={"data": rows if isinstance(rows, list) else [rows]},
            metrics={"recipients": float(sent), "notified": 1.0,
                     "total_rows": float(total) if total is not None else float(count),
                     "threshold_rows": float(threshold)},
        )


@register_operator
class RetrainThresholdOperator(BaseOperator):
    id = "retrain_threshold"
    name = "Retrain Threshold"
    category = "closed_loop"
    description = ("Trigger AutoML retraining once the accumulated dataset "
                   "reaches the row threshold; completes the model swap on a "
                   "later invoke when the job finishes")
    inputs = [PortSpec("data", "DataTable", "Accumulated Rows")]
    outputs = [
        PortSpec("triggered", "DataTable", "Triggered"),
        PortSpec("continue", "DataTable", "Below Threshold"),
    ]
    parameters = [
        ParamSpec("dataset_artifact_id", "str", "", "Accumulated Dataset Artifact ID", required=True),
        ParamSpec("retrain_dataset_artifact_id", "str", "", "Retrain Dataset Artifact ID", required=True),
        # 目标列只在**监督**范式必填——无监督（异常检测）重训无目标列，画布层
        # 强制填写会挡住无监督节点。运行时按部署范式校验（见 execute 内
        # _deployment_is_anomaly）：监督缺目标列仍报原错误，无监督放行。
        ParamSpec("retrain_target_column", "str", "", "Retrain Target Column"),
        ParamSpec("threshold_rows", "int", 12, "Threshold Rows", range_min=1),
        ParamSpec("retrain_max_trials", "int", 10, "Max Trials", range_min=5),
        # 编排闭环重训的终选层集成（多模型加权投票）：与闭环自动化配置同义，
        # 不低于单模型冠军才成为任务冠军并参与换模（仅单输出分类）。
        ParamSpec("retrain_ensemble_enabled", "boolean", False, "Retrain Ensemble (weighted voting)"),
        ParamSpec("retrain_ensemble_top_k", "int", 3, "Ensemble Members (top-K)", range_min=2, range_max=5),
        # 向导算法白名单（逗号分隔，空=全族）与重训特征列白名单（逗号分隔，
        # 空=全部数值列；稀疏宽表必配——缺列行被引擎 dropna 整行剔除）。
        ParamSpec("retrain_algorithm_ids", "str", "", "Retrain Algorithm Whitelist (comma separated, empty = all families)"),
        ParamSpec("retrain_input_columns", "str", "", "Retrain Feature Columns (comma separated, empty = all numeric)"),
        ParamSpec("swap_deployment_id", "str", "", "Deployment ID to swap after completion"),
    ]

    def validate(self, inputs):
        return True

    @staticmethod
    def _deployment_is_anomaly(context, params) -> bool:
        """目标列必填性按部署范式判定：服务版本 output_schema.task=="anomaly"
        即无监督部署（无目标列）。解析失败一律按监督处理（fail-closed 报错）。"""
        deployment_id = str(params.get("swap_deployment_id") or "").strip()
        if not deployment_id or context.artifact_service is None:
            return False
        try:
            import uuid as _uuid

            from app.models.model_registry import (
                InferenceDeployment,
                ModelVersion,
            )

            db = context.artifact_service.db
            deployment = db.query(InferenceDeployment).filter(
                InferenceDeployment.id == _uuid.UUID(deployment_id),
            ).first()
            if deployment is None or deployment.model_version_id is None:
                return False
            version = db.query(ModelVersion).filter(
                ModelVersion.id == deployment.model_version_id,
            ).first()
            if version is None:
                return False
            schema = version.output_schema if isinstance(version.output_schema, dict) else {}
            return str(schema.get("task") or "") == "anomaly"
        except Exception:  # noqa: BLE001 - 范式探测失败按监督处理
            return False

    def execute(self, context: OperatorContext, inputs, params) -> OperatorResult:
        from app.models.training import TrainingJob
        from app.services.closed_loop_actions import (
            complete_retrain_swap,
            trigger_retrain_job,
        )
        artifact_id = str(params.get("dataset_artifact_id") or "").strip()
        target_column = str(params.get("retrain_target_column") or "").strip()
        threshold = max(1, int(params.get("threshold_rows") or 12))
        if not artifact_id:
            raise RuntimeError("dataset_artifact_id is required")
        if not target_column and not self._deployment_is_anomaly(context, params):
            # 无监督（异常检测）部署无目标列——按部署范式放行；监督缺列仍报错。
            raise RuntimeError("retrain_target_column is required")
        if context.artifact_service is None or not context.project_id:
            raise RuntimeError("Artifact service and project context are required")
        db = context.artifact_service.db
        artifact = context.artifact_service.resolve(
            artifact_id, context.project_id, expected_type="dataset",
        )
        meta = dict(artifact.metadata_ or {})
        total = int(meta.get("row_count", 0))
        # Rolling cycle base: accumulated rows since the last swap/trigger.
        cycle_base = int(meta.get("cycle_base", 0))

        def _save_meta():
            artifact.metadata_ = meta
            db.commit()

        # Advance a pending retrain cycle: swap the deployment once its AutoML
        # job completed (state lives on the dataset artifact metadata).
        job_id = meta.get("retrain_job_id")
        if job_id:
            try:
                job = db.query(TrainingJob).filter(
                    TrainingJob.id == uuid.UUID(str(job_id)),
                ).first()
            except (TypeError, ValueError, AttributeError):
                job = None
            if job is None or job.status == "failed":
                meta["retrain_job_id"] = None
                meta["retrain_failed"] = True
                _save_meta()
            elif job.status == "completed" and not meta.get("swapped_model_version_id"):
                if not context.operator_id:
                    raise RuntimeError("operator context lacks an actor id")
                version = complete_retrain_swap(
                    db,
                    deployment_id=params.get("swap_deployment_id") or None,
                    job=job,
                    actor_id=context.operator_id,
                    model_name="编排闭环-自动模型",
                )
                meta["retrain_job_id"] = None
                if version is not None:
                    meta["swapped_model_version_id"] = str(version.id)
                meta["cycle_base"] = total
                _save_meta()

        pending = bool(meta.get("retrain_job_id"))
        # Recalculate cycle_rows AFTER the swap block (which updates cycle_base).
        cycle_base = int(meta.get("cycle_base", 0))
        cycle_rows = total - cycle_base
        triggered_row = {"triggered": False, "total_rows": total,
                         "cycle_rows": cycle_rows, "threshold_rows": threshold}
        continue_row = {"total_rows": total, "remaining": max(0, threshold - cycle_rows)}
        if not pending and cycle_rows >= threshold:
            if not context.operator_id:
                raise RuntimeError("operator context lacks an actor id")
            # 绑定表以 experiment_id 为主键，且重训幂等指纹含实验名；图重新
            # 发布后 total 会重置，实验名必须带周期 token 防止冲突与重放。
            cycle = uuid.uuid4().hex[:8]
            # 画布参数可能以字符串形态到达（"true"/"3"），统一宽松解析；top_k 钳制 2-5
            ensemble_flag = params.get("retrain_ensemble_enabled")
            ensemble_enabled = ensemble_flag is True or str(ensemble_flag).strip().lower() in {"true", "1", "yes"}
            try:
                ensemble_top_k = max(2, min(5, int(params.get("retrain_ensemble_top_k") or 3)))
            except (TypeError, ValueError):
                ensemble_top_k = 3

            def _split_csv(key: str) -> list[str] | None:
                values = [
                    item.strip() for item in str(params.get(key) or "").split(",") if item.strip()
                ]
                return values or None

            job = trigger_retrain_job(
                db,
                project_id=context.project_id,
                actor_id=context.operator_id,
                experiment_name=f"编排闭环-{total}-{cycle}",
                job_name=f"编排闭环-自动建模-{total}-{cycle}",
                dataset_artifact_id=params.get("retrain_dataset_artifact_id") or artifact.id,
                target_column=target_column,
                max_trials=int(params.get("retrain_max_trials") or 10),
                ensemble={"enabled": True, "top_k": ensemble_top_k} if ensemble_enabled else None,
                algorithm_ids=_split_csv("retrain_algorithm_ids"),
                input_columns=_split_csv("retrain_input_columns"),
            )
            meta["retrain_job_id"] = str(job.id)
            meta["cycle_base"] = total
            _save_meta()
            triggered_row["triggered"] = True
            triggered_row["job_id"] = str(job.id)
        return OperatorResult(
            outputs={"triggered": [triggered_row], "continue": [continue_row]},
            metrics={"total_rows": float(total)},
        )


@register_operator
class AgentRetrainThresholdOperator(BaseOperator):
    """编排闭环的智能体重训触发器（闭环自动化分类）。

    与闭环自动化 retrain_mode=agent 同链路：报错回流行累积到增量阈值后，
    复用绑定的固化配方（guidance 快照）重放智能体全流程（S1 分析→S2 特征
    沙箱→S3 验收训练（lightweight_trainer，函数名为历史遗留，默认全量）
    →S4 硬门禁+评审），验收通过后固化新配方并由引擎铸造
    部署模型换模（配方门禁兜底）。护栏与闭环一致：部署级单飞（在途不重
    触发）、增量边沿触发（换模成功推进基线）、冷却期与 24h 熔断（触顶转
    管理员通知）。状态存累积数据集工件 metadata，每次图执行推进一轮状态
    机；DB 访问统一走 loop_retrain 的查询 helper。"""

    id = "agent_retrain_threshold"
    name = "Agent Retrain Threshold"
    category = "closed_loop"
    description = ("Replay the full agent pipeline (analysis/features/modeling/"
                   "acceptance) from the fixated recipe once accumulated rows "
                   "reach the threshold; the engine then mints the deployment "
                   "model and swaps after acceptance")
    inputs = [PortSpec("data", "DataTable", "Accumulated Rows")]
    outputs = [
        PortSpec("triggered", "DataTable", "Triggered"),
        PortSpec("continue", "DataTable", "Below Threshold"),
    ]
    parameters = [
        ParamSpec("dataset_artifact_id", "str", "", "Accumulated Dataset Artifact ID", required=True),
        ParamSpec("retrain_dataset_artifact_id", "str", "", "Retrain Dataset Artifact ID", required=True),
        # 目标列只在**监督**范式必填——无监督（异常检测）配方无目标列，画布层
        # 强制填写会挡住无监督节点。范式由配方固化内容判定（services/agent/
        # loop_retrain.detect_recipe_paradigm），运行时监督缺列仍报原错误。
        ParamSpec("retrain_target_column", "str", "", "Retrain Target Column"),
        ParamSpec("agent_recipe_id", "str", "", "Fixated Recipe ID (with guidance snapshot)", required=True),
        ParamSpec("swap_deployment_id", "str", "", "Deployment ID to swap after completion", required=True),
        ParamSpec("threshold_rows", "int", 12, "Threshold Rows", range_min=1),
        ParamSpec("retrain_max_trials", "int", 10, "Max Trials", range_min=5),
        ParamSpec("retrain_ensemble_enabled", "boolean", False, "Casting Ensemble (weighted voting)"),
        ParamSpec("retrain_ensemble_top_k", "int", 3, "Ensemble Members (top-K)", range_min=2, range_max=5),
        ParamSpec("retrain_algorithm_ids", "str", "", "Casting Algorithm Whitelist (comma separated, empty = all families)"),
        ParamSpec("retrain_input_columns", "str", "", "Retrain Feature Columns (comma separated, empty = all numeric)"),
    ]

    def validate(self, inputs):
        return True

    def execute(self, context, inputs, params):
        # 执行体宿主 services/agent/loop_retrain.orchestration_agent_retrain_execute
        #（Mimosa 对本文件新增 execute 存在概念形态误报死锁，见 loop_retrain.py
        # docstring；人工复核无 SQL 拼接）
        from app.services.agent.loop_retrain import orchestration_agent_retrain_execute

        return orchestration_agent_retrain_execute(context, inputs, params)
