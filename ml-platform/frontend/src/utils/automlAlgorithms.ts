// 模型版本里记录的算法 id → 展示名（AutoML 族名与建模页 AUTOML_ALGORITHM_OPTIONS 保持一致）
const ALGORITHM_LABELS: Record<string, string> = {
  lightgbm: "LightGBM",
  xgboost: "XGBoost",
  catboost: "CatBoost",
  gbdt: "GBDT",
  random_forest: "Random Forest",
  extra_trees: "Extra Trees",
  hist_gradient_boosting: "HistGradientBoosting",
  mlp: "MLP 神经网络",
  iforest: "IsolationForest 隔离森林",
  ocsvm: "One-Class SVM 单类支持向量机",
  autoencoder: "AutoEncoder 自编码器",
  ensemble: "集成加权投票",
  onnx: "ONNX",
};

/** 未收录的 id 原样展示 */
export function algorithmLabel(id: string | null | undefined): string {
  const key = (id ?? "").trim();
  return ALGORITHM_LABELS[key] ?? key;
}
