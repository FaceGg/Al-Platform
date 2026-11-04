"""经验受益对比 harness（集成判据③，spec §16.5 RSI 收益验证）。

对同一数据集/同一 LLM 档案做 A/B 两臂 Agent 任务：

- 处理臂（treatment）：平台经验库当前 active 条目正常注入（L2 检索）；
- 对照臂（control）：同一批条目临时置为 retired（不注入），跑完恢复。

每臂各跑 --runs-per-arm 次 AgentRun（真实 DeepSeek S1/S2/S4 + 真实 S3
训练器），对比两臂的 S3 指标均值（recall_minority/f1/accuracy）与 token
消耗，输出对比报告。

用法（需已配置真实 LLM 档案，会产生真实 token 消耗）：
    python tools/acceptance/run_experience_comparison.py \
        --frame-csv <数据.csv> --target-col <目标列> \
        --profile-name "<DB 内 LLM 档案名>" --runs-per-arm 2

可选：--domain tightening（经验检索域，默认 tightening）；
--apply 实际执行（默认 dry-run 只打印计划）；--keep-runs 保留 AgentRun
记录（默认跑完删除两臂的运行行）。
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

os.environ.setdefault("LLM_MASTER_KEY", os.environ.get("LLM_MASTER_KEY", ""))

# 处理臂基线（--control-only 补数据时引用）：2026-11-04 实测 accepted 运行
# （280 行平衡拧紧样本，9 条 cross-domain 经验注入，max_rounds=6）
TREATMENT_BASELINE = [{
    "run_id": "2be1053f-ca99-4ae5-b7f0-388d70989f82",
    "status": "accepted",
    "recall_minority": 1.0,
    "f1": 0.9836,
    "accuracy": 0.9857,
    "total_tokens": None,
}]


def _parse_args():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--frame-csv", required=True)
    parser.add_argument("--target-col", required=True)
    parser.add_argument("--profile-name", required=True)
    parser.add_argument("--runs-per-arm", type=int, default=2)
    parser.add_argument("--domain", default="tightening")
    parser.add_argument("--apply", action="store_true",
                        help="实际执行（默认 dry-run）")
    parser.add_argument("--keep-runs", action="store_true")
    parser.add_argument("--max-rounds", type=int, default=6,
                        help="AgentRun guidance max_rounds（默认 6，让两臂跑到门禁判定）")
    parser.add_argument("--control-only", action="store_true",
                        help="只跑对照臂（处理臂已有 accepted 结果时补数据用）")
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    frame_path = Path(args.frame_csv)
    if not frame_path.is_file():
        print(f"数据文件不存在: {frame_path}")
        return 2

    import uuid

    import pandas as pd

    from app.config import settings as app_settings
    from app.database import Base, SessionLocal, engine
    from app.models.agent_run import AgentRun
    from app.models.experience_entry import ExperienceEntry
    from app.models.llm_profile import LLMProfile
    from app.models.project import Project
    from app.models.user import User
    from app.services.agent.executor import execute_agent_run
    from app.services.artifact_service import build_artifact_service
    from app.services.llm_profile_crypto import encrypt_llm_api_key

    Base.metadata.create_all(bind=engine)
    frame = pd.read_csv(frame_path)
    if args.target_col not in frame.columns:
        print(f"目标列不在数据中: {args.target_col}")
        return 2

    db = SessionLocal()
    try:
        profile = (
            db.query(LLMProfile)
            .filter(LLMProfile.name == args.profile_name)
            .first()
        )
        if profile is None:
            print(f"DB 内找不到 LLM 档案: {args.profile_name}")
            return 2
        admin = db.query(User).filter(User.username == "admin").one()
        project = Project(name=f"集成判据A-B实验-{uuid.uuid4().hex[:8]}", owner_id=admin.id)
        db.add(project)
        db.flush()
        service = build_artifact_service(db)
        artifact = service.create_from_file(
            project.id, frame_path,
            f"exp-cmp-{uuid.uuid4().hex[:6]}", "dataset",
        )
        db.commit()
        # 纯值捕获：ORM 对象随会话关闭过期，跨会话只带标量 id
        project_id = project.id
        artifact_id = artifact.id
        profile_id = profile.id
        admin_id = admin.id
        print(f"project={project_id} artifact={artifact_id} rows={len(frame)}")

        experience_ids = [
            str(entry.id)
            for entry in db.query(ExperienceEntry)
            .filter(
                ExperienceEntry.status == "active",
                ExperienceEntry.domain.in_([args.domain, "cross-domain"]),
            )
            .all()
        ]
        print(f"active 经验条目（{args.domain}/cross-domain）: {len(experience_ids)} 条")
        if not args.apply:
            print("dry-run：加 --apply 实际执行（产生真实 token 消耗）")
            return 0
    finally:
        db.close()

    def run_arm(label: str) -> dict:
        db = SessionLocal()
        run_ids: list[str] = []
        try:
            if label == "control":
                # 对照臂：退役当前全部 active（含处理臂蒸馏晋升的新条目——
                # 否则 RSI 命中晋升会把处理臂新蒸馏条目注入对照臂，A/B 污染）
                db.query(ExperienceEntry).filter(
                    ExperienceEntry.status == "active",
                ).update({"status": "retired"}, synchronize_session=False)
                db.commit()
            metrics_rows = []
            for index in range(args.runs_per_arm):
                run = AgentRun(
                    project_id=project_id,
                    dataset_artifact_id=artifact_id,
                    target_column=args.target_col,
                    llm_profile_id=profile_id,
                    guidance_json={"max_rounds": args.max_rounds},
                    created_by=admin_id,
                )
                db.add(run)
                db.commit()
                run_ids.append(str(run.id))
                print(f"[{label} #{index + 1}] executing {run.id} ...")
                execute_agent_run(str(run.id))
                # 身份映射缓存会返回创建时的 pending 行——过期后再读终态
                db.expire_all()
                refreshed = db.get(AgentRun, run.id)
                agent_metrics = (refreshed.result_json or {}).get("metrics") or {}
                usage = (refreshed.result_json or {}).get("usage") or {}
                metrics_rows.append({
                    "run_id": str(run.id),
                    "status": refreshed.status,
                    "recall_minority": agent_metrics.get("recall_minority"),
                    "f1": agent_metrics.get("f1"),
                    "accuracy": agent_metrics.get("accuracy"),
                    "total_tokens": usage.get("total_tokens"),
                })
                print(f"  -> {metrics_rows[-1]}")
            return {"label": label, "runs": metrics_rows}
        finally:
            db.close()

    results = []
    try:
        if not args.control_only:
            results.append(run_arm("treatment"))
        else:
            # 补数据模式：处理臂沿用既有 accepted 运行（见台账）
            results.append({"label": "treatment", "runs": TREATMENT_BASELINE})
        results.append(run_arm("control"))
    finally:
        # 无论成败只恢复"原 active 集"（处理臂蒸馏的新条目保持其自然状态，
        # 由 RSI 命中晋升/退役机制接管，不越权转正）
        if experience_ids:
            db = SessionLocal()
            try:
                db.query(ExperienceEntry).filter(
                    ExperienceEntry.id.in_(experience_ids),
                ).update({"status": "active"}, synchronize_session=False)
                db.commit()
            finally:
                db.close()

    def _mean(rows, key):
        values = [r[key] for r in rows if isinstance(r.get(key), (int, float))]
        return sum(values) / len(values) if values else None

    print("\n===== 经验受益对比报告 =====")
    for key in ("recall_minority", "f1", "accuracy", "total_tokens"):
        treatment = _mean(results[0]["runs"], key)
        control = _mean(results[1]["runs"], key)
        if treatment is None or control is None:
            print(f"{key}: 数据不足（treatment={treatment} control={control}）")
            continue
        delta = treatment - control
        print(f"{key}: treatment={treatment:.4f} control={control:.4f} delta={delta:+.4f}")

    if not args.keep_runs:
        db = SessionLocal()
        try:
            all_ids = [r["run_id"] for arm in results for r in arm["runs"]]
            db.query(AgentRun).filter(AgentRun.id.in_(all_ids)).delete(
                synchronize_session=False,
            )
            db.commit()
            print("已清理两臂 AgentRun 记录（--keep-runs 可保留）")
        finally:
            db.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
