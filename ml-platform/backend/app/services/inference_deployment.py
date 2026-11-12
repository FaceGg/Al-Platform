"""Inference deployment desired/observed state orchestration."""

from datetime import datetime, timezone
import hashlib
import json
import logging
import uuid
from pathlib import Path

from app.events.domain import create_domain_event, to_storage_payload
from app.models.artifact import Artifact
from app.models.model_registry import (
    DeploymentRevision,
    DeploymentRollout,
    DeploymentTarget,
    InferenceDeployment,
    ModelVersion,
)
from app.services.artifact_service import build_artifact_service
from app.services.inference_rollout import ConditionValueRouter
from app.services.inference_runtime_client import InferenceRuntimeClientError

logger = logging.getLogger(__name__)


def utcnow():
    return datetime.now(timezone.utc).replace(tzinfo=None)


class InferenceDeploymentError(RuntimeError):
    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


# 部署版本标定阈值缓存（§6.6A 推理判定统一）：version 不可变，进程级缓存
_ANOMALY_THRESHOLD_CACHE: dict[str, float] = {}


def anomaly_threshold_for_version(db, version):
    """部署版本的标定阈值（score_stats.threshold_score，§6.6A）。

    链：版本 → 模型库（training_job_id）→ 训练任务 metrics.score_artifact_id
    → 工件 JSON。工况分片版本（M7）优先走 conversion_metadata 里注册时写入的
    anomaly_score_stats_artifact_id——每分片独立标定，job 顶层 score_artifact_id
    是最差段的，直接复用会张冠李戴。任一环节缺失返回 None（调用方回退 label
    端口判定）。
    """
    cached = _ANOMALY_THRESHOLD_CACHE.get(str(version.id))
    if cached is not None:
        return cached
    try:
        from app.models.model_library import ModelLibrary
        from app.models.training import TrainingJob

        metadata = version.conversion_metadata if isinstance(version.conversion_metadata, dict) else {}
        shard_stats_id = str(metadata.get("anomaly_score_stats_artifact_id") or "").strip()
        if shard_stats_id:
            # JSON 列取出的 id 恒为 str：UUID 列绑定必须转 uuid 对象（既往坑）
            artifact = db.query(Artifact).filter(
                Artifact.id == uuid.UUID(shard_stats_id),
            ).first()
            if artifact is not None:
                service = build_artifact_service(db)
                with service.materialize(artifact.id, artifact.project_id, expected_type="report") as path:
                    payload = json.loads(Path(path).read_text(encoding="utf-8"))
                threshold = payload.get("threshold_score")
                if threshold is not None:
                    value = float(threshold)
                    _ANOMALY_THRESHOLD_CACHE[str(version.id)] = value
                    return value
        library = db.query(ModelLibrary).filter(
            ModelLibrary.id == version.source_model_library_id,
        ).first()
        if library is None or not library.training_job_id:
            return None
        job = db.query(TrainingJob).filter(TrainingJob.id == library.training_job_id).first()
        score_artifact_id = (job.metrics or {}).get("score_artifact_id") if job else None
        if not score_artifact_id:
            return None
        artifact = db.query(Artifact).filter(Artifact.id == str(score_artifact_id)).first()
        if artifact is None:
            return None
        service = build_artifact_service(db)
        with service.materialize(artifact.id, job.project_id, expected_type="report") as path:
            payload = json.loads(Path(path).read_text(encoding="utf-8"))
        threshold = payload.get("threshold_score")
        return float(threshold) if threshold is not None else None
    except Exception:
        return None


def anomaly_predict_enrichment(runtime, runtime_key, records, result, *,
                               feature_schema, output_schema, threshold_score=None,
                               enable_attribution=True):
    """无监督三要素映射 + 单行扰动归因（技术方案 §3.5，平台/生产端点共用）。

    ONNX `scores` 端口 = sklearn decision_function（正=正常，2026-11-12
    双族实测），anomaly_score 取负统一为「越高越异常」。§6.6A 判定统一：
    is_anomaly 按 anomaly_score ≥ threshold_score（训练标定阈值，随版本
    score_stats 下发）；threshold 不可得时回退 label 端口（offset 语义）。
    top_contributors 用中心差分扰动归因（每特征 ±1% 各重推理一次，共
    2×n_features 次 session.run），仅单行请求时返回——批量归因成本线性
    放大，一期不做。enable_attribution=False 供工况分片批量路径禁用
    （按总请求数判断归因，防分片子组恰为单行时成本线性放大）。非 anomaly
    部署原样返回。
    """
    schema = output_schema if isinstance(output_schema, dict) else {}
    if schema.get("task") != "anomaly":
        return result
    probabilities = result.get("probabilities")
    predictions = result.get("predictions")
    if probabilities is None or predictions is None:
        return result
    result["anomaly_score"] = [-float(value) for value in probabilities]
    if threshold_score is not None:
        result["is_anomaly"] = [
            float(value) >= float(threshold_score) for value in result["anomaly_score"]
        ]
    else:
        result["is_anomaly"] = [int(value) == -1 for value in predictions]
    names = [
        str(item.get("name"))
        for item in (feature_schema or [])
        if isinstance(item, dict) and item.get("name")
    ]
    if enable_attribution and len(records) == 1 and names:
        row = dict(records[0])
        contributions: list[dict[str, float | str]] = []
        for name in names:
            base_value = float(row.get(name) or 0.0)
            step = max(abs(base_value) * 0.01, 1e-6)
            up = dict(row)
            up[name] = base_value + step
            down = dict(row)
            down[name] = base_value - step
            up_score = -float(runtime.predict(runtime_key, [up])["probabilities"][0])
            down_score = -float(runtime.predict(runtime_key, [down])["probabilities"][0])
            contributions.append({
                "feature": name,
                "contribution": (up_score - down_score) / (2.0 * step),
            })
        contributions.sort(key=lambda item: abs(float(item["contribution"])), reverse=True)
        result["top_contributors"] = contributions[:3]
    return result


class InferenceDeploymentService:
    def __init__(self, runtime_client, session_factory):
        self.runtime = runtime_client
        self.session_factory = session_factory

    @staticmethod
    def _uuid(value, code):
        try:
            return uuid.UUID(str(value))
        except (TypeError, ValueError, AttributeError):
            raise InferenceDeploymentError(code) from None

    def create(self, db, *, project_id, version_id, actor_id, name, commit=True):
        project_uuid = self._uuid(project_id, "PROJECT_NOT_FOUND")
        version_uuid = self._uuid(version_id, "MODEL_VERSION_NOT_FOUND")
        version = db.query(ModelVersion).filter(
            ModelVersion.id == version_uuid,
        ).first()
        if version is None or version.registered_model.project_id != project_uuid:
            raise InferenceDeploymentError("MODEL_VERSION_NOT_FOUND")
        if version.approval_status != "approved":
            raise InferenceDeploymentError("MODEL_NOT_APPROVED")
        normalized_name = str(name).strip()
        if not normalized_name or len(normalized_name) > 128:
            raise InferenceDeploymentError("DEPLOYMENT_NAME_INVALID")
        deployment = InferenceDeployment(
            project_id=project_uuid,
            name=normalized_name,
            model_version_id=version.id,
            desired_state="stopped",
            observed_state="stopped",
            created_by_id=actor_id,
        )
        db.add(deployment)
        db.flush()
        self._ensure_stable_revision(db, deployment, actor_id)
        if commit:
            db.commit()
            db.refresh(deployment)
        else:
            db.flush()
        return deployment

    @staticmethod
    def _ensure_stable_revision(db, deployment, actor_id=None):
        revision = db.query(DeploymentRevision).filter(
            DeploymentRevision.deployment_id == deployment.id,
            DeploymentRevision.status == "stable",
        ).order_by(DeploymentRevision.revision_number.desc()).first()
        if revision is not None:
            return revision
        latest = db.query(DeploymentRevision.revision_number).filter(
            DeploymentRevision.deployment_id == deployment.id,
        ).order_by(DeploymentRevision.revision_number.desc()).first()
        revision = DeploymentRevision(
            deployment_id=deployment.id,
            revision_number=(int(latest[0]) if latest else 0) + 1,
            strategy="immediate",
            status="stable",
            created_by_id=actor_id,
        )
        db.add(revision)
        db.flush()
        db.add(DeploymentTarget(
            revision_id=revision.id,
            model_version_id=deployment.model_version_id,
            weight_bps=10000,
            role="stable",
        ))
        db.flush()
        return revision

    def _deployment(self, db, deployment_id, lock=False):
        deployment_uuid = self._uuid(
            deployment_id, "INFERENCE_DEPLOYMENT_NOT_FOUND"
        )
        query = db.query(InferenceDeployment).filter(
            InferenceDeployment.id == deployment_uuid,
        )
        if lock:
            query = query.with_for_update()
        deployment = query.first()
        if deployment is None:
            raise InferenceDeploymentError("INFERENCE_DEPLOYMENT_NOT_FOUND")
        return deployment

    @staticmethod
    def _specification(db, deployment, revision=None):
        if revision is None:
            revision = db.query(DeploymentRevision).filter(
                DeploymentRevision.deployment_id == deployment.id,
                DeploymentRevision.status == "stable",
            ).order_by(DeploymentRevision.revision_number.desc()).first()
        model_version_id = deployment.model_version_id
        if revision is not None and revision.targets:
            model_version_id = sorted(
                revision.targets,
                key=lambda target: (-int(target.weight_bps), str(target.model_version_id)),
            )[0].model_version_id
        version = db.query(ModelVersion).filter(
            ModelVersion.id == model_version_id,
        ).one()
        artifact = db.query(Artifact).filter(
            Artifact.id == version.onnx_artifact_id,
        ).one()
        metadata = version.conversion_metadata or {}
        return {
            "runtime_key": str(deployment.id),
            "deployment_id": str(deployment.id),
            "revision_id": str(revision.id) if revision is not None else None,
            "model_version_id": str(version.id),
            "version_number": version.version_number,
            "storage_uri": artifact.storage_uri,
            "sha256": metadata.get("sha256") or (artifact.metadata_ or {}).get("sha256"),
            "size": int(metadata.get("size") or artifact.file_size or 0),
            "feature_schema": version.feature_schema,
            "output_schema": version.output_schema,
            "input_names": metadata.get("input_names", []),
            "output_names": metadata.get("output_names", []),
        }

    @staticmethod
    def _target_specification(db, deployment, revision, target):
        version = db.query(ModelVersion).filter(
            ModelVersion.id == target.model_version_id,
        ).one()
        artifact = db.query(Artifact).filter(
            Artifact.id == version.onnx_artifact_id,
        ).one()
        metadata = version.conversion_metadata or {}
        return {
            "runtime_key": f"{revision.id}:{target.model_version_id}",
            "deployment_id": str(deployment.id),
            "revision_id": str(revision.id),
            "model_version_id": str(version.id),
            "version_number": version.version_number,
            "storage_uri": artifact.storage_uri,
            "sha256": metadata.get("sha256") or (artifact.metadata_ or {}).get("sha256"),
            "size": int(metadata.get("size") or artifact.file_size or 0),
            "feature_schema": version.feature_schema,
            "output_schema": version.output_schema,
            "input_names": metadata.get("input_names", []),
            "output_names": metadata.get("output_names", []),
        }

    def _load_stable_aliases(self, db, deployment, loaded_keys=None):
        revision = db.query(DeploymentRevision).filter(
            DeploymentRevision.deployment_id == deployment.id,
            DeploymentRevision.status == "stable",
        ).order_by(DeploymentRevision.revision_number.desc()).first()
        if revision is None:
            return
        loaded_keys = loaded_keys if loaded_keys is not None else set()
        for target in revision.targets or ():
            runtime_key = f"{revision.id}:{target.model_version_id}"
            if runtime_key in loaded_keys:
                continue
            self.runtime.load(
                runtime_key,
                self._target_specification(db, deployment, revision, target),
            )
            loaded_keys.add(runtime_key)

    def _runtime_keys_for_stop(self, db, deployment):
        """Find legacy and revision runtime keys belonging to deployment."""
        deployment_id = str(deployment.id)
        runtime_keys = {deployment_id}
        stable = db.query(DeploymentRevision).filter(
            DeploymentRevision.deployment_id == deployment.id,
            DeploymentRevision.status == "stable",
        ).order_by(DeploymentRevision.revision_number.desc()).first()
        revisions = [stable] if stable is not None else []
        active_rollouts = db.query(DeploymentRollout).filter(
            DeploymentRollout.deployment_id == deployment.id,
            DeploymentRollout.state.in_(("pending", "preloading", "progressing", "paused")),
        ).all()
        revisions.extend(rollout.to_revision for rollout in active_rollouts)
        for revision in revisions:
            runtime_keys.update(
                f"{revision.id}:{target.model_version_id}"
                for target in revision.targets or ()
            )

        lister = getattr(self.runtime, "list", None)
        if callable(lister):
            for item in (lister().get("items", []) or ()):
                if str(item.get("deployment_id")) != deployment_id:
                    continue
                runtime_key = item.get("runtime_key") or item.get("deployment_id")
                if runtime_key:
                    runtime_keys.add(str(runtime_key))
        return runtime_keys

    @staticmethod
    def _runtime_code(error):
        return getattr(error, "code", "INFERENCE_RUNTIME_UNAVAILABLE")

    def start(self, db, deployment_id):
        deployment = self._deployment(db, deployment_id, lock=True)
        if deployment.desired_state == "running" and deployment.observed_state == "running":
            # 已运行部署不重复走装载状态机，但 stable 换目标后（如闭环换模）
            # 新的 revision 别名尚未加载；同身份重复 load 是 no-op，安全。
            self._load_stable_aliases(db, deployment)
            return deployment
        deployment.desired_state = "running"
        deployment.observed_state = "starting"
        deployment.last_error_code = None
        db.commit()
        specification = self._specification(db, deployment)
        try:
            self.runtime.load(deployment.id, specification)
            self._load_stable_aliases(db, deployment, {str(deployment.id)})
        except Exception as error:
            deployment = self._deployment(db, deployment.id, lock=True)
            deployment.observed_state = "failed"
            deployment.last_error_code = self._runtime_code(error)
            deployment.last_checked_at = utcnow()
            db.commit()
            raise InferenceDeploymentError(deployment.last_error_code) from None
        deployment = self._deployment(db, deployment.id, lock=True)
        deployment.observed_state = "running"
        deployment.last_error_code = None
        deployment.started_at = utcnow()
        deployment.last_checked_at = utcnow()
        db.commit()
        db.refresh(deployment)
        return deployment

    def stop(self, db, deployment_id):
        deployment = self._deployment(db, deployment_id, lock=True)
        if deployment.desired_state == "stopped" and deployment.observed_state == "stopped":
            return deployment
        deployment.desired_state = "stopped"
        deployment.observed_state = "stopping"
        deployment.last_error_code = None
        db.commit()
        try:
            runtime_keys = self._runtime_keys_for_stop(db, deployment)
            first_error = None
            for runtime_key in sorted(runtime_keys):
                try:
                    self.runtime.unload(runtime_key)
                except Exception as error:
                    first_error = first_error or error
            if first_error is not None:
                raise first_error
        except Exception as error:
            deployment = self._deployment(db, deployment.id, lock=True)
            deployment.observed_state = "failed"
            deployment.last_error_code = self._runtime_code(error)
            deployment.last_checked_at = utcnow()
            db.commit()
            raise InferenceDeploymentError(deployment.last_error_code) from None
        deployment = self._deployment(db, deployment.id, lock=True)
        deployment.observed_state = "stopped"
        deployment.stopped_at = utcnow()
        deployment.last_checked_at = utcnow()
        db.commit()
        db.refresh(deployment)
        return deployment

    def predict(self, db, deployment_id, records, routing_key=None):
        deployment = self._deployment(db, deployment_id)
        if deployment.desired_state != "running" or deployment.observed_state != "running":
            raise InferenceDeploymentError("DEPLOYMENT_NOT_READY")
        try:
            condition_column = str(getattr(deployment, "condition_column", None) or "").strip()
            if condition_column:
                # 工况分片路由（§6.3）：部署声明 condition_column 即工况模式，
                # 与灰度 routing_key 互斥（灰度键在工况模式下被忽略）。
                return self.predict_condition_sharded(db, deployment, condition_column, records)
            runtime_key = deployment.id
            if routing_key is not None:
                from app.services.inference_rollout import WeightedTargetRouter

                routed = WeightedTargetRouter().select_active(deployment, routing_key)
                stable = db.query(DeploymentRevision).filter(
                    DeploymentRevision.deployment_id == deployment.id,
                    DeploymentRevision.status == "stable",
                ).order_by(DeploymentRevision.revision_number.desc()).first()
                if (
                    stable is None
                    or str(routed.revision_id) != str(stable.id)
                    or str(routed.model_version_id) != str(deployment.model_version_id)
                ):
                    runtime_key = f"{routed.revision_id}:{routed.model_version_id}"
            else:
                # 默认路径跟随换模：换模只轮换 revision（旧键仍载旧模型，别名由
                # reconcile ≤60s 预载），不带 rollout 路由的调用此前永远打旧模型
                # （闭环实测 716e5803：换模后 predict 仍返回 v1）。路由到最新
                # stable revision 的别名；别名尚未预载时回落旧键（窗口 ≤1 个
                # reconcile 周期，行为与旧版一致）。
                stable = db.query(DeploymentRevision).filter(
                    DeploymentRevision.deployment_id == deployment.id,
                    DeploymentRevision.status == "stable",
                ).order_by(DeploymentRevision.revision_number.desc()).first()
                if stable is not None and str(deployment.model_version_id) and any(
                    str(target.model_version_id) == str(deployment.model_version_id)
                    for target in stable.targets or ()
                ):
                    runtime_key = f"{stable.id}:{deployment.model_version_id}"
            try:
                result = self.runtime.predict(runtime_key, records)
                used_key = runtime_key
            except InferenceRuntimeClientError as alias_error:
                if runtime_key != deployment.id and "DEPLOYMENT_NOT_READY" in str(alias_error):
                    used_key = deployment.id
                    result = self.runtime.predict(deployment.id, records)
                else:
                    raise
            except InferenceDeploymentError as alias_error:
                # 仅"别名未载"回落（换模后 ≤60s 窗口）；别名的真实推理错误照常上抛
                if runtime_key != deployment.id and getattr(alias_error, "code", "") == "DEPLOYMENT_NOT_READY":
                    used_key = deployment.id
                    result = self.runtime.predict(deployment.id, records)
                else:
                    raise
            # 无监督三要素（技术方案 §3.5）：按实际服务版本的 output_schema 分支。
            # runtime_key 初值是 deployment.id（UUID 对象），统一按字符串比较。
            if str(used_key) == str(deployment.id):
                served_version_id = deployment.model_version_id
            else:
                served_version_id = uuid.UUID(str(used_key).split(":", 1)[1])
            served_version = db.query(ModelVersion).filter(
                ModelVersion.id == served_version_id,
            ).one()
            served_threshold = anomaly_threshold_for_version(db, served_version)
            return self._anomaly_enrich(
                used_key, records, result, served_version,
                threshold_score=served_threshold,
            )
        except (InferenceRuntimeClientError, InferenceDeploymentError) as error:
            raise InferenceDeploymentError(self._runtime_code(error)) from None

    def predict_condition_sharded(self, db, deployment, condition_column, records):
        """工况分片推理（技术方案 §6.3，二期 M7）：按记录工况值分组路由。

        - targets 从最新 stable revision 解析（revision 不可变；分片 targets
          由闭环换模挂载，各自带 condition_value 标注）
        - 每组独立 runtime.predict（键 ``{revision_id}:{model_version_id}``，
          与灰度共用 reconcile 预载）+ 按该组实际服务版本独立 enrich——每
          分片阈值独立（conversion_metadata.anomaly_score_stats_artifact_id）
        - 未命中回退默认分片（ConditionValueRouter：condition_value=None 通配
          优先，再则 weight 最高）并落 unknown_condition 审计事件（同一
          unknown 集合幂等只落一次）
        - 响应附逐记录 ``condition_values`` 回显（排障用；分片选择对调用方
          透明，三要素合同不变）；单行请求保留 top_contributors 归因
        """
        stable = db.query(DeploymentRevision).filter(
            DeploymentRevision.deployment_id == deployment.id,
            DeploymentRevision.status == "stable",
        ).order_by(DeploymentRevision.revision_number.desc()).first()
        if stable is None or not (stable.targets or ()):
            raise InferenceDeploymentError("STABLE_REVISION_NOT_FOUND")
        router = ConditionValueRouter(condition_column)
        groups: dict[tuple[str, str | None], list[int]] = {}
        condition_values: list[str | None] = []
        unknown_values: set[str] = set()
        for index, record in enumerate(records):
            routed = router.select_for_record(deployment, record, targets=stable.targets)
            groups.setdefault(
                (str(routed.model_version_id), routed.condition_value),
                [],
            ).append(index)
            # 回显语义：None=该记录未精确命中任何分片（走了兜底，详情见
            # unknown_condition 审计事件）；命中时回显实际服务的工况值。
            condition_values.append(routed.condition_value if routed.matched else None)
            raw_value = record.get(condition_column)
            if not routed.matched and raw_value not in (None, ""):
                unknown_values.add(str(raw_value))
        if unknown_values:
            self._record_unknown_condition_event(
                db, deployment, condition_column, unknown_values,
            )
        merged: dict = {"condition_values": condition_values}
        list_keys = ("predictions", "probabilities", "anomaly_score", "is_anomaly")
        for key in list_keys:
            merged[key] = [None] * len(records)
        single_row_contributors = None
        for model_version_id, _condition_value in groups:
            version = db.query(ModelVersion).filter(
                ModelVersion.id == uuid.UUID(model_version_id),
            ).first()
            if version is None:
                raise InferenceDeploymentError("MODEL_VERSION_NOT_FOUND")
            runtime_key = f"{stable.id}:{model_version_id}"
            sub_records = [records[index] for index in groups[(model_version_id, _condition_value)]]
            try:
                result = self.runtime.predict(runtime_key, sub_records)
                used_key = runtime_key
            except (InferenceRuntimeClientError, InferenceDeploymentError) as alias_error:
                # 别名未载回落主键（换模后 ≤1 个 reconcile 周期窗口；主版本
                # 即默认分片，回落语义与单模型路径一致）
                if (
                    getattr(alias_error, "code", "") == "DEPLOYMENT_NOT_READY"
                    or "DEPLOYMENT_NOT_READY" in str(alias_error)
                ):
                    used_key = str(deployment.id)
                    result = self.runtime.predict(deployment.id, sub_records)
                else:
                    raise
            served_threshold = anomaly_threshold_for_version(db, version)
            enriched = anomaly_predict_enrichment(
                self.runtime, used_key, sub_records, result,
                feature_schema=version.feature_schema,
                output_schema=version.output_schema,
                threshold_score=served_threshold,
                enable_attribution=len(records) == 1,
            )
            if not isinstance(enriched, dict):
                raise InferenceDeploymentError("INFERENCE_PREDICT_INVALID")
            for key in list_keys:
                values = enriched.get(key)
                if isinstance(values, list):
                    for position, index in enumerate(groups[(model_version_id, _condition_value)]):
                        if position < len(values):
                            merged[key][index] = values[position]
            if len(records) == 1 and enriched.get("top_contributors") is not None:
                single_row_contributors = enriched.get("top_contributors")
        if single_row_contributors is not None:
            merged["top_contributors"] = single_row_contributors
        return merged

    def _record_unknown_condition_event(self, db, deployment, condition_column, values):
        """unknown_condition 审计事件（§6.3）：未命中分片的工况值集合落域事件。

        幂等键含集合指纹——同一 unknown 集合只落一次；savepoint 隔离，落库
        失败不影响推理本身。
        """
        from sqlalchemy.dialects.postgresql import insert as postgresql_insert
        from sqlalchemy.dialects.sqlite import insert as sqlite_insert

        from app.models.notifications import NotificationOutbox

        fingerprint = hashlib.sha256(
            "|".join(sorted(values)).encode("utf-8"),
        ).hexdigest()[:16]
        event = create_domain_event(
            idempotency_key=f"inference.unknown_condition:{deployment.id}:{fingerprint}",
            event_type="inference.unknown_condition",
            severity="warning",
            occurred_at=utcnow(),
            project_id=deployment.project_id,
            actor_id=None,
            resource_type="inference_deployment",
            resource_id=str(deployment.id),
            payload={
                "condition_column": condition_column,
                "unknown_values": sorted(values),
            },
        )
        try:
            with db.begin_nested():
                statement_factory = (
                    postgresql_insert
                    if db.get_bind().dialect.name == "postgresql"
                    else sqlite_insert
                )
                db.execute(statement_factory(NotificationOutbox).values(
                    id=uuid.uuid4(),
                    event_id=event.event_id,
                    idempotency_key=event.idempotency_key,
                    event_type=event.event_type,
                    severity=event.severity,
                    occurred_at=event.occurred_at.replace(tzinfo=None),
                    project_id=event.project_id,
                    actor_id=event.actor_id,
                    resource_type=event.resource_type,
                    resource_id=event.resource_id,
                    payload=to_storage_payload(event.payload),
                    status="pending",
                ).on_conflict_do_nothing(
                    index_elements=[NotificationOutbox.idempotency_key],
                ))
        except Exception:  # noqa: BLE001 - 审计事件失败不阻断推理
            logger.warning(
                "unknown_condition event persist failed (deployment=%s)",
                deployment.id,
                exc_info=True,
            )

    def _anomaly_enrich(self, runtime_key, records, result, version, threshold_score,
                        enable_attribution=True):
        return anomaly_predict_enrichment(
            self.runtime, runtime_key, records, result,
            feature_schema=version.feature_schema,
            output_schema=version.output_schema,
            threshold_score=threshold_score,
            enable_attribution=enable_attribution,
        )

    def reconcile(self, db, *, include_rollout_aliases=False):
        runtime_items = self.runtime.list().get("items", [])
        runtime_ids = {
            str(item.get("runtime_key") or item["deployment_id"])
            for item in runtime_items
        }
        desired = db.query(InferenceDeployment).all()
        loaded = unloaded = failed = 0
        desired_ids = {str(item.id) for item in desired if item.desired_state == "running"}
        expected_runtime_ids = set(desired_ids)
        for deployment in desired:
            if deployment.desired_state != "running":
                continue
            stable_revision = db.query(DeploymentRevision).filter(
                DeploymentRevision.deployment_id == deployment.id,
                DeploymentRevision.status == "stable",
            ).order_by(DeploymentRevision.revision_number.desc()).first()
            if stable_revision is not None:
                expected_runtime_ids.update(
                    f"{stable_revision.id}:{target.model_version_id}"
                    for target in stable_revision.targets or ()
                )
        active_rollouts = db.query(DeploymentRollout).filter(
            DeploymentRollout.state.in_(("pending", "preloading", "progressing", "paused")),
        ).all()
        for rollout in active_rollouts:
            if str(rollout.deployment_id) not in desired_ids:
                continue
            revision = rollout.to_revision
            expected_runtime_ids.update(
                f"{revision.id}:{target.model_version_id}"
                for target in revision.targets or ()
            )
            if not include_rollout_aliases:
                continue
            for target in revision.targets or ():
                runtime_key = f"{revision.id}:{target.model_version_id}"
                if runtime_key in runtime_ids:
                    continue
                try:
                    self.runtime.load(
                        runtime_key,
                        self._target_specification(db, rollout.deployment, revision, target),
                    )
                    runtime_ids.add(runtime_key)
                    loaded += 1
                except Exception as error:
                    failed += 1
        for deployment in desired:
            try:
                expected_runtime_key = str(deployment.id)
                if deployment.desired_state == "running" and expected_runtime_key not in runtime_ids:
                    self.runtime.load(deployment.id, self._specification(db, deployment))
                    runtime_ids.add(expected_runtime_key)
                    deployment.observed_state = "running"
                    deployment.last_error_code = None
                    loaded += 1
                if deployment.desired_state == "running":
                    self._load_stable_aliases(db, deployment, runtime_ids)
                elif deployment.desired_state == "stopped" and str(deployment.id) in runtime_ids:
                    self.runtime.unload(deployment.id)
                    deployment.observed_state = "stopped"
                    deployment.last_error_code = None
                    unloaded += 1
                deployment.last_checked_at = utcnow()
            except Exception as error:
                deployment.observed_state = "failed"
                deployment.last_error_code = self._runtime_code(error)
                deployment.last_checked_at = utcnow()
                failed += 1
        for orphan_id in runtime_ids - expected_runtime_ids:
            if not any(str(item.id) == orphan_id for item in desired):
                try:
                    self.runtime.unload(orphan_id)
                    unloaded += 1
                except Exception:
                    failed += 1
        db.commit()
        return {"loaded": loaded, "unloaded": unloaded, "failed": failed}
