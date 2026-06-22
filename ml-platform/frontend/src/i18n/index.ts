import { createContext, useContext } from "react";

type Lang = "zh" | "en";

const translations = {
  zh: {
    app: { title: "ML 算法平台", login: "登录", logout: "退出登录", register: "注册" },
    nav: { dashboard: "工作台", projects: "项目", models: "模型库", data: "数据浏览", users: "用户管理" },
    project: { create: "新建项目", name: "项目名称", desc: "描述", list: "项目列表" },
    workspace: { run: "运行", save: "保存", nodes: "算子", settings: "设置", search_operator: "搜索算子...", delete_workflow: "删除工作流", save_success: "已保存", save_failed: "保存失败", run_failed: "执行失败", back: "返回", operator_panel: "算子面板", run_progress: "执行进度", select_node_hint: "选择一个节点查看属性", node_properties: "节点属性", params_config: "参数配置", no_params: "无参数配置", execution_status: "执行状态", status: "状态:", result_preview: "结果预览" },
    template: { welding: "焊接质量预测", next: "下一步", create_and_run: "创建并运行" },
    operator: {
      csv_import: "CSV/Excel 导入", data_table: "数据表格", data_stats: "数据统计",
      missing_value: "缺失值处理", label_encoder: "特征编码", scaler: "特征缩放",
      train_test_split: "数据划分", xgboost_train: "XGBoost 训练", random_forest: "随机森林",
      linear_model: "线性模型", classification_eval: "分类评估", regression_eval: "回归评估",
      roc_curve: "ROC 曲线", feature_importance: "特征重要性", distribution: "分布图",
      mlp: "MLP 分类器", mlp_reg: "MLP 回归器", cnn1d: "1D CNN 分类器"
    },
    common: { loading: "加载中...", error: "错误", success: "成功", confirm: "确认", cancel: "取消", delete: "删除" },
    profile: { admin: "管理员", engineer: "工程师", user: "用户" },
    model: { title: "模型库", version: "版本", created: "创建时间", actions: "操作" },
    knowledge: {
      title: "知识库", create: "创建知识库", name: "名称", desc: "描述",
      upload: "上传文档", search: "搜索", chat: "智能对话",
      send: "发送", sources: "参考来源", graph: "知识图谱",
      entity: "实体", relation: "关系", add_entity: "添加实体",
      entity_name: "名称", entity_type: "类型", relation_type: "关系类型",
      doc_count: "文档数", delete_kb: "确认删除知识库", delete_kb_desc: "此操作不可撤销。",
    },
    monitor: {
      title: "资源监控", cpu: "CPU", memory: "内存", disk: "磁盘",
      gpu: "GPU", usage: "使用率", total: "总量", used: "已用", refresh: "刷新",
    },
    data: {
      import: "导入数据", export: "导出数据", batch: "批量导入",
      format: "格式", preview: "预览", label: "标注数据", title: "数据管理",
      upload_file: "上传文件", filename: "文件名", size: "大小", rows: "行数",
      delete_file: "确认删除文件", download: "下载",
    },
    automl: {
      title: "自动化建模", run: "运行 AutoML", target: "目标列", task: "任务类型",
      budget: "时间预算(秒)", results: "结果", best_model: "最佳模型",
      score: "得分", all_results: "所有结果", select_dataset: "选择数据集",
      select_project: "选择项目",
    },
    training: {
      title: "模型训练", jobs: "训练任务", status: "状态",
      params: "参数", metrics: "指标", operator: "算子", started: "开始时间",
    },
  },
  en: {
    app: { title: "ML Platform", login: "Login", logout: "Logout", register: "Register" },
    nav: { dashboard: "Dashboard", projects: "Projects", models: "Models", data: "Data Browser", users: "User Management" },
    project: { create: "New Project", name: "Project Name", desc: "Description", list: "Projects" },
    workspace: { run: "Run", save: "Save", nodes: "Nodes", settings: "Settings", search_operator: "Search operators...", delete_workflow: "Delete Workflow", save_success: "Saved", save_failed: "Save Failed", run_failed: "Execution Failed", back: "Back", operator_panel: "Operators", run_progress: "Progress", select_node_hint: "Select a node to view properties", node_properties: "Node Properties", params_config: "Parameters", no_params: "No parameters", execution_status: "Execution Status", status: "Status:", result_preview: "Result Preview" },
    template: { welding: "Weld Quality Prediction", next: "Next", create_and_run: "Create & Run" },
    operator: {
      csv_import: "CSV/Excel Import", data_table: "Data Table", data_stats: "Data Statistics",
      missing_value: "Missing Value Handler", label_encoder: "Label Encoder", scaler: "Scaler",
      train_test_split: "Train/Test Split", xgboost_train: "XGBoost Trainer", random_forest: "Random Forest",
      linear_model: "Linear Model", classification_eval: "Classification Eval", regression_eval: "Regression Eval",
      roc_curve: "ROC Curve", feature_importance: "Feature Importance", distribution: "Distribution Plot",
      mlp: "MLP Classifier", mlp_reg: "MLP Regressor", cnn1d: "1D CNN Classifier"
    },
    common: { loading: "Loading...", error: "Error", success: "Success", confirm: "Confirm", cancel: "Cancel", delete: "Delete" },
    profile: { admin: "Admin", engineer: "Engineer", user: "User" },
    model: { title: "Model Library", version: "Version", created: "Created", actions: "Actions" },
    knowledge: {
      title: "Knowledge Base", create: "Create KB", name: "Name", desc: "Description",
      upload: "Upload", search: "Search", chat: "Chat",
      send: "Send", sources: "Sources", graph: "Knowledge Graph",
      entity: "Entity", relation: "Relation", add_entity: "Add Entity",
      entity_name: "Name", entity_type: "Type", relation_type: "Relation Type",
      doc_count: "Docs", delete_kb: "Delete Knowledge Base", delete_kb_desc: "This action cannot be undone.",
    },
    monitor: {
      title: "Monitor", cpu: "CPU", memory: "Memory", disk: "Disk",
      gpu: "GPU", usage: "Usage", total: "Total", used: "Used", refresh: "Refresh",
    },
    data: {
      import: "Import", export: "Export", batch: "Batch Import",
      format: "Format", preview: "Preview", label: "Label", title: "Data Management",
      upload_file: "Upload File", filename: "Filename", size: "Size", rows: "Rows",
      delete_file: "Delete File", download: "Download",
    },
    automl: {
      title: "AutoML", run: "Run AutoML", target: "Target Column", task: "Task Type",
      budget: "Time Budget(s)", results: "Results", best_model: "Best Model",
      score: "Score", all_results: "All Results", select_dataset: "Select Dataset",
      select_project: "Select Project",
    },
    training: {
      title: "Training", jobs: "Jobs", status: "Status",
      params: "Params", metrics: "Metrics", operator: "Operator", started: "Started",
    },
  }
};

export type TranslationKeys = typeof translations.en;
export const LangContext = createContext<{lang: Lang; t: TranslationKeys; setLang: (l: Lang) => void}>({
  lang: "zh", t: translations.zh, setLang: () => {}
});
export const useI18n = () => useContext(LangContext);
export { translations };
