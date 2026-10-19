// 工作流算子悬停说明的中英文映射。
// zh 为必配项（后端 description 多为英文）；en 可选——缺省时回落到后端 description
// （对后端本就是英文的算子无需重复配置）。
export const operatorDescriptions: Record<string, { zh: string; en?: string }> = {
  // ---- 数据输入输出 (io) ----
  csv_import: { zh: "导入 CSV / Excel 数据文件" },
  read_excel: { zh: "读取 Excel 数据文件" },
  read_database: { zh: "通过 SQL 从数据库读取数据" },
  read_url: { zh: "从 URL 地址读取数据" },
  json_import: { zh: "导入 JSON 数据文件" },
  image_import: { zh: "导入图片文件元数据" },
  csv_export: { zh: "将数据导出为 CSV 文件" },
  write_csv: { zh: "将数据写出为 CSV 文件" },
  store: { zh: "将数据集存入数据仓库" },
  retrieve: { zh: "从数据仓库取回已存数据集" },
  api_input: { zh: "编排 API 调用时注入的记录（仅在 API 调用内可用）" },
  append_error_dataset: { zh: "将分支数据追加到错误数据集（闭环回流）" },
  notify_admins: { zh: "向项目负责人和平台管理员发送站内通知" },

  // ---- 数据处理 (processing) ----
  missing_value_handler: { zh: "处理数据集中的缺失值（删除或填充）" },
  impute_missing_advanced: { zh: "高级缺失值填充" },
  label_encoder: { zh: "对分类列进行编码（标签编码 / 独热编码）" },
  scaler: { zh: "数值特征缩放（标准化 / 最小最大 / 鲁棒）" },
  normalize: { zh: "数值列归一化 / 标准化" },
  discretize: { zh: "将连续值按箱体离散化" },
  detect_outliers: { zh: "检测数值型数据中的离群点" },
  filter_examples: { zh: "按表达式过滤数据行" },
  sample: { zh: "对数据随机抽样" },
  select_attributes: { zh: "选择 / 过滤数据列" },
  set_role: { zh: "设置列角色（标签、ID、权重等）" },
  train_test_split: { zh: "将数据划分为训练集与测试集" },
  auto_feature_engineering: { zh: "自动生成与筛选特征：对选中的数值列生成交互项，再按打分筛选（可限定特征列范围）" },

  // ---- 特征工程 (feature_engineering) ----
  spot_weld_feature_engineering: { zh: "解码四路报告波形，生成固定 73 维点焊特征" },
  tighten_feature_engineering: { zh: "拧紧质量特征派生：扭矩偏差、公差带位置、上下限余量、双轴扭矩差" },

  // ---- 数据融合 (blending) ----
  join: { zh: "按键列连接两个数据集" },
  union: { zh: "纵向合并数据集，自动匹配列" },
  aggregate: { zh: "按列分组并计算聚合值" },
  pivot: { zh: "行列透视（输出透视表 + 逆向预处理模型）" },
  transpose: { zh: "行列转置" },
  generate_attributes: { zh: "通过 Python 表达式新建一列" },
  sort: { zh: "按列排序数据" },

  // ---- 流程控制 (control) ----
  condition: { zh: "条件分支：按条件路由数据" },
  merge: { zh: "将多条数据流合并为一路" },
  loop: { zh: "循环执行：按配置迭代处理数据" },
  retrain_threshold: {
    zh: "回流数据累积到阈值后自动触发 AutoML 重训，任务完成后自动换模上线",
    en: "Trigger AutoML retraining once the accumulated dataset reaches the row threshold; completes the model swap on a later invoke",
  },

  // ---- 机器学习 (ml) ----
  linear_model_train: { zh: "训练线性模型（回归或分类）" },
  random_forest_train: { zh: "训练随机森林模型" },
  decision_tree: { zh: "训练决策树分类器" },
  naive_bayes: { zh: "训练朴素贝叶斯分类器" },
  knn: { zh: "K 近邻（k-NN）分类器" },
  svm: { zh: "支持向量机（SVM）分类器" },
  logistic_regression: {
    zh: "逻辑回归分类器，支持二分类 / 多分类目标列训练",
    en: "Logistic regression classifier for binary/multiclass targets",
  },
  svm_regression: {
    zh: "支持向量回归（SVR）模型训练",
    en: "Support vector regression trained on the input data",
  },
  random_forest_regression: {
    zh: "随机森林回归模型训练",
    en: "Random forest regressor trained on the input data",
  },
  xgboost_train: { zh: "训练 XGBoost 模型" },
  kmeans_clustering: {
    zh: "k-Means 聚类，聚类标签追加到输入数据",
    en: "k-Means clustering that appends cluster labels to the input data",
  },
  dbscan: {
    zh: "DBSCAN 密度聚类，聚类标签追加到输入数据（噪声点为 -1）",
    en: "DBSCAN density-based clustering that appends cluster labels; noise points are -1",
  },
  apriori: {
    zh: "Apriori 关联规则挖掘，按支持度 / 置信度阈值提取规则",
    en: "Apriori association-rule mining over transaction data",
  },
  fp_growth: {
    zh: "FP-Growth 关联规则挖掘，基于 FP 树提取规则",
    en: "FP-Growth association-rule mining over transaction data",
  },
  apply_model: { zh: "将已训练模型应用到数据并追加预测列" },
  load_model_artifact: { zh: "加载已冻结的模型制品用于推理服务" },

  // ---- 深度学习 (dl) ----
  mlp_classifier: { zh: "基于 PyTorch 训练多层感知机（MLP）分类器" },
  mlp_regressor: { zh: "基于 PyTorch 训练多层感知机（MLP）回归器" },
  cnn1d_classifier: { zh: "基于 PyTorch 训练一维卷积（1D-CNN）分类器" },

  // ---- 模型评估 (evaluation) ----
  classification_eval: { zh: "评估分类模型性能（accuracy / P / R / F1 + 混淆矩阵）" },
  classification_eval_detailed: { zh: "分类详细评估：每类指标、错误分析、F1 曲线" },
  cross_validation: {
    zh: "k-折交叉验证，评估模型泛化能力",
    en: "k-fold cross-validation to estimate generalization performance",
  },
  model_comparison: { zh: "多个训练模型在同一测试集上对比" },
  regression_eval: { zh: "评估回归模型性能" },
  anomaly_eval: { zh: "将无监督异常标记与已知故障标签对比评估" },

  // ---- 可视化 (visualization) ----
  data_table: { zh: "表格视图展示数据" },
  data_stats: { zh: "计算数据集统计信息" },
  histogram: { zh: "绘制数值列直方图" },
  bar_chart: {
    zh: "生成柱状图展示分类数据",
    en: "Bar chart for categorical data",
  },
  line_chart: { zh: "绘制一列或多列的折线图" },
  scatter_plot: { zh: "绘制两数值列散点图" },
  box_plot: { zh: "绘制数值列箱线图" },
  distribution_plot: { zh: "绘制数值列分布图" },
  confusion_matrix_plot: { zh: "根据评估结果绘制混淆矩阵" },
  roc_curve: { zh: "绘制分类模型 ROC 曲线" },
  feature_importance: { zh: "绘制训练模型的特征重要性" },

  // ---- 机理模型 (mechanism) ----
  mechanism_thermal: {
    zh: "基于 Fourier 导热定律计算点焊熔核温度场分布与热影响区半径，验证参数合理性",
    en: "Compute nugget temperature field and HAZ radius via Fourier conduction; validates process parameters",
  },
  mechanism_nugget: {
    zh: "基于焦耳热方程预测点焊熔核直径与熔深，评估连接强度是否达标",
    en: "Predict nugget diameter and penetration depth via Joule heating; assesses joint strength",
  },
  mechanism_lobe: {
    zh: "计算点焊可焊参数窗口（电流 / 通电时间上下限），判断参数是否落在窗口内",
    en: "Compute the weldability lobe (current/time bounds) and check whether parameters fall inside",
  },
  mechanism_splash: {
    zh: "综合能量密度、动态压力与加热速率，预测点焊飞溅发生概率与风险等级",
    en: "Predict spatter probability from energy density, dynamic pressure and heating rate",
  },
  mechanism_stress: {
    zh: "基于热弹塑性简化模型估算冷却后残余应力与变形倾向",
    en: "Estimate residual stress and deformation tendency after cooling",
  },
  mechanism_gate: {
    zh: "串联全部 5 个机理模型，对焊接参数做一站式物理约束检查，输出汇总与综合风险等级",
    en: "Chain all five mechanism models for one-shot physical constraint checking with risk level",
  },

  // ---- 参数优化 (optimization) ----
  optimize_grid: { zh: "网格搜索超参数优化" },
  optimize_evolutionary: { zh: "进化算法超参数优化" },

  // ---- 工具 (utility) ----
  collect: { zh: "将多路数据输入拼接为一路" },
  macro: { zh: "定义流水线宏变量，数据原样透传" },
  python_script: {
    zh: "在隔离子进程中运行 Python 脚本（df 进、result 出）；脚本缺失的 import 依赖按服务端配置的软件源自动安装",
    en: "Run a Python script in an isolated subprocess (df in, result out); missing imports are auto-installed from server-configured sources",
  },
  write_as_text: { zh: "将数据预览 / 摘要写出为文本文件（调试用）" },
};
