"""模型统一命名：模型库条目与模型下拉展示统一为「项目名称-实验名称-算法名称」。"""


def compose_model_name(*segments: object) -> str:
    """按「项目名称-实验名称-算法名称」拼接，跳过空段并限制总长度。"""
    parts = [str(segment or "").strip() for segment in segments]
    return "-".join(part for part in parts if part)[:256]


def artifact_experiment_name(job) -> str:
    """任务关联的实验名，缺失时回退任务名。"""
    experiment = getattr(job, "experiment", None)
    if experiment is not None:
        name = str(getattr(experiment, "name", "") or "").strip()
        if name:
            return name
    return str(getattr(job, "name", "") or "").strip()


def artifact_display_name(artifact, project_name: str, jobs_by_id: dict) -> str:
    """模型工件在下拉中的展示名。

    自动建模/训练产物 → 项目-实验-算法；来源任务已删时实验段不可考，
    退化为项目-算法；手动上传等无法解析关联的保持原名。
    """
    metadata = artifact.metadata_ or {}
    job = jobs_by_id.get(str(metadata.get("training_job_id") or ""))
    algorithm = str(metadata.get("best_algorithm") or "").strip()
    if job is not None:
        base = artifact_experiment_name(job)
        last = algorithm or str(job.name or "").strip()
        if last and last != base:
            return compose_model_name(project_name, base, last)
        return compose_model_name(project_name, base)
    if str(metadata.get("source") or "") == "automl" and algorithm:
        return compose_model_name(project_name, algorithm)
    return artifact.name
