from app.templates.contract import (
    IndustrialTemplate,
    TemplateEdge,
    TemplateExpectedOutput,
    TemplateNode,
    TemplateParameter,
)


IDENTITY_AND_TARGET = ("Car Body", "Welding Spot", "Date", "Fault")
TEMPLATE_DATASET_ARTIFACT_ID = "__injected_at_instantiation__"


def node(key, operator_id, label, x, y, **params):
    return TemplateNode(key, operator_id, label, x, y, params)


def edge(source, source_port, target, target_port):
    return TemplateEdge(source, source_port, target, target_port)


COMMON_IMPORT = node(
    "import", "csv_import", "导入焊接特征", 40, 140,
    source="artifact", dataset_artifact_id=TEMPLATE_DATASET_ARTIFACT_ID,
)
COMMON_CLEAN = node("clean", "missing_value_handler", "缺失值处理", 250, 140, strategy="median", fill_value="", columns="")
COMMON_SCALE = node("scale", "scaler", "特征缩放", 460, 140, method="standard", columns="", target_column="Fault")
COMMON_SPLIT = node(
    "split", "train_test_split", "训练测试划分", 670, 140,
    test_size=0.2, random_seed=42, target_column="Fault", stratify=True,
)


INDUSTRIAL_TEMPLATES = {
    "weld_quality": IndustrialTemplate(
        id="weld_quality", name="焊接质量预测",
        description="基于电流、电压和压力统计特征预测焊点故障。",
        scenario="Fault 二分类", task_type="classification", target_column="Fault",
        required_columns=IDENTITY_AND_TARGET,
        nodes=(COMMON_IMPORT, COMMON_CLEAN, COMMON_SCALE, COMMON_SPLIT,
               node("train", "random_forest_train", "随机森林训练", 900, 80,
                    target_column="Fault", task="classification", n_estimators=100,
                    max_depth=10, random_seed=42, class_weight="balanced"),
               node("evaluation", "classification_eval_detailed", "故障分类评估", 1130, 140,
                    target_column="Fault", threshold=0.5)),
        edges=(edge("import", "data", "clean", "data"), edge("clean", "data", "scale", "data"),
               edge("scale", "data", "split", "data"), edge("split", "train", "train", "data"),
               edge("train", "model", "evaluation", "model"), edge("split", "test", "evaluation", "test")),
        parameters=(TemplateParameter("n_estimators", "树的数量", "int", 100, (("train", "n_estimators"),)),),
        expected_outputs=(TemplateExpectedOutput("evaluation", "metrics"),
                          TemplateExpectedOutput("evaluation", "per_label"),
                          TemplateExpectedOutput("evaluation", "chart")),
    ),
    "fault_parameter_analysis": IndustrialTemplate(
        id="fault_parameter_analysis", name="故障风险参数分析",
        description="识别与 Fault 风险相关的关键电流、电压和压力特征。",
        scenario="故障风险分类与特征重要性", task_type="classification", target_column="Fault",
        required_columns=IDENTITY_AND_TARGET,
        nodes=(COMMON_IMPORT, COMMON_CLEAN, COMMON_SCALE, COMMON_SPLIT,
               node("train", "random_forest_train", "风险分类模型", 900, 80,
                    target_column="Fault", task="classification", n_estimators=150,
                    max_depth=8, random_seed=42, class_weight="balanced"),
               node("evaluation", "classification_eval_detailed", "风险分类评估", 1130, 60,
                    target_column="Fault", threshold=0.5),
               node("importance", "feature_importance", "关键参数排序", 1130, 230,
                    target_column="Fault", top_n=12)),
        edges=(edge("import", "data", "clean", "data"), edge("clean", "data", "scale", "data"),
               edge("scale", "data", "split", "data"), edge("split", "train", "train", "data"),
               edge("train", "model", "evaluation", "model"), edge("split", "test", "evaluation", "test"),
               edge("train", "model", "importance", "model"), edge("split", "test", "importance", "data")),
        parameters=(TemplateParameter("n_estimators", "树的数量", "int", 150, (("train", "n_estimators"),)),),
        expected_outputs=(TemplateExpectedOutput("evaluation", "metrics"),
                          TemplateExpectedOutput("importance", "chart")),
    ),
    "anomaly_detection": IndustrialTemplate(
        id="anomaly_detection", name="焊接异常检测",
        description="使用无监督异常检测标记异常焊点，并输出异常统计。",
        scenario="无监督异常检测", task_type="anomaly_detection", target_column="Fault",
        required_columns=IDENTITY_AND_TARGET,
        nodes=(COMMON_IMPORT, COMMON_SCALE,
               node("detect", "detect_outliers", "异常检测", 700, 140,
                    method="isolation_forest", contamination=0.05,
                    exclude_columns="Car Body,Welding Spot,Fault"),
               node("statistics", "data_stats", "异常统计", 930, 70),
               node("evaluation", "anomaly_eval", "故障命中评估", 930, 220,
                    target_column="Fault", flag_column="outlier")),
        edges=(edge("import", "data", "scale", "data"), edge("scale", "data", "detect", "data"),
               edge("detect", "data", "statistics", "data"),
               edge("detect", "data", "evaluation", "data")),
        parameters=(TemplateParameter("contamination", "预计异常比例", "float", 0.05,
                                      (("detect", "contamination"),)),),
        expected_outputs=(TemplateExpectedOutput("detect", "data"),
                          TemplateExpectedOutput("statistics", "stats"),
                          TemplateExpectedOutput("evaluation", "metrics")),
    ),
    "full_ml_comparison": IndustrialTemplate(
        id="full_ml_comparison", name="全流程多模型对比",
        description="共享预处理后比较随机森林与 XGBoost 的 Fault 分类表现。",
        scenario="多模型分类对比", task_type="classification", target_column="Fault",
        required_columns=IDENTITY_AND_TARGET,
        nodes=(COMMON_IMPORT, COMMON_CLEAN, COMMON_SCALE, COMMON_SPLIT,
               node("rf_train", "random_forest_train", "随机森林训练", 900, 40,
                    target_column="Fault", task="classification", n_estimators=120,
                    max_depth=10, random_seed=42, class_weight="balanced"),
               node("xgb_train", "xgboost_train", "XGBoost 训练", 900, 220,
                    target_column="Fault", task="classification", n_estimators=100,
                    max_depth=5, learning_rate=0.1, random_seed=42, scale_pos_weight=24.0),
               node("rf_eval", "classification_eval_detailed", "随机森林评估", 1130, 20,
                    target_column="Fault", threshold=0.5),
               node("xgb_eval", "classification_eval_detailed", "XGBoost 评估", 1130, 210,
                    target_column="Fault", threshold=0.5),
               node("comparison", "model_comparison", "模型对比", 1360, 120,
                    target_column="Fault", metric="f1")),
        edges=(edge("import", "data", "clean", "data"), edge("clean", "data", "scale", "data"),
               edge("scale", "data", "split", "data"), edge("split", "train", "rf_train", "data"),
               edge("split", "train", "xgb_train", "data"), edge("rf_train", "model", "rf_eval", "model"),
               edge("split", "test", "rf_eval", "test"), edge("xgb_train", "model", "xgb_eval", "model"),
               edge("split", "test", "xgb_eval", "test"), edge("rf_train", "model", "comparison", "model_a"),
               edge("xgb_train", "model", "comparison", "model_b"), edge("split", "test", "comparison", "test")),
        parameters=(TemplateParameter("rf_estimators", "随机森林树数量", "int", 120,
                                      (("rf_train", "n_estimators"),)),
                    TemplateParameter("xgb_estimators", "XGBoost 树数量", "int", 100,
                                      (("xgb_train", "n_estimators"),))),
        expected_outputs=(TemplateExpectedOutput("rf_eval", "metrics"),
                          TemplateExpectedOutput("xgb_eval", "metrics"),
                          TemplateExpectedOutput("comparison", "comparison")),
    ),
}
