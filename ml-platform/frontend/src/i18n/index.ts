import { createContext, useContext } from "react";

type Lang = "zh" | "en";

const zh = {
    app: { title: "AI\u6a21\u578b\u8bad\u7ec3\u7f16\u6392\u5e73\u53f0", login: "\u767b\u5f55", logout: "\u9000\u51fa\u767b\u5f55", register: "\u6ce8\u518c" },
    nav: { dashboard: "\u5de5\u4f5c\u53f0", projects: "\u9879\u76ee", models: "\u6a21\u578b\u5e93", data: "\u6570\u636e\u7ba1\u7406", users: "\u7528\u6237\u7ba1\u7406" },
    project: { create: "\u65b0\u5efa\u9879\u76ee", name: "\u9879\u76ee\u540d\u79f0", desc: "\u63cf\u8ff0", list: "\u9879\u76ee\u5217\u8868" },
    workspace: { run: "\u8fd0\u884c", save: "\u4fdd\u5b58", nodes: "\u7b97\u5b50", settings: "\u8bbe\u7f6e", search_operator: "\u641c\u7d22\u7b97\u5b50...", delete_workflow: "\u5220\u9664\u5de5\u4f5c\u6d41", save_success: "\u5df2\u4fdd\u5b58", save_failed: "\u4fdd\u5b58\u5931\u8d25", run_failed: "\u6267\u884c\u5931\u8d25", back: "\u8fd4\u56de", operator_panel: "\u7b97\u5b50\u9762\u677f", run_progress: "\u6267\u884c\u8fdb\u5ea6", select_node_hint: "\u9009\u62e9\u4e00\u4e2a\u8282\u70b9\u67e5\u770b\u5c5e\u6027", node_properties: "\u8282\u70b9\u5c5e\u6027", params_config: "\u53c2\u6570\u914d\u7f6e", no_params: "\u65e0\u53c2\u6570\u914d\u7f6e", execution_status: "\u6267\u884c\u72b6\u6001", status: "\u72b6\u6001:", result_preview: "\u7ed3\u679c\u9884\u89c8" },
    template: { welding: "\u710a\u63a5\u8d28\u91cf\u9884\u6d4b", param_recommend: "\u53c2\u6570\u63a8\u8350", anomaly_detect: "\u5f02\u5e38\u68c0\u6d4b", full_ml: "\u5168\u6d41\u7a0bML\u5efa\u6a21", next: "\u4e0b\u4e00\u6b65", create_and_run: "\u521b\u5efa\u5e76\u8fd0\u884c" },
    operator: {
      csv_import: "CSV/Excel \u5bfc\u5165", data_table: "\u6570\u636e\u8868\u683c", data_stats: "\u6570\u636e\u7edf\u8ba1",
      missing_value: "\u7f3a\u5931\u503c\u5904\u7406", label_encoder: "\u7279\u5f81\u7f16\u7801", scaler: "\u7279\u5f81\u7f29\u653e",
      train_test_split: "\u6570\u636e\u5212\u5206", xgboost_train: "XGBoost \u8bad\u7ec3", random_forest: "\u968f\u673a\u68ee\u6797",
      linear_model: "\u7ebf\u6027\u6a21\u578b", classification_eval: "\u5206\u7c7b\u8bc4\u4f30", regression_eval: "\u56de\u5f52\u8bc4\u4f30",
      roc_curve: "ROC \u66f2\u7ebf", feature_importance: "\u7279\u5f81\u91cd\u8981\u6027", distribution: "\u5206\u5e03\u56fe",
      mlp: "MLP \u5206\u7c7b\u5668", mlp_reg: "MLP \u56de\u5f52\u5668", cnn1d: "1D CNN \u5206\u7c7b\u5668",
    },
    common: { loading: "\u52a0\u8f7d\u4e2d...", error: "\u9519\u8bef", success: "\u6210\u529f", confirm: "\u786e\u8ba4", cancel: "\u53d6\u6d88", delete: "\u5220\u9664" },
    profile: { admin: "\u7ba1\u7406\u5458", engineer: "\u5de5\u7a0b\u5e08", user: "\u7528\u6237" },
    model: { title: "\u6a21\u578b\u5e93", version: "\u7248\u672c", created: "\u521b\u5efa\u65f6\u95f4", actions: "\u64cd\u4f5c" },
    knowledge: {
      title: "\u77e5\u8bc6\u5e93", create: "\u521b\u5efa\u77e5\u8bc6\u5e93", name: "\u540d\u79f0", desc: "\u63cf\u8ff0",
      upload: "\u4e0a\u4f20\u6587\u6863", search: "\u641c\u7d22", chat: "\u667a\u80fd\u5bf9\u8bdd",
      send: "\u53d1\u9001", sources: "\u53c2\u8003\u6765\u6e90", graph: "\u77e5\u8bc6\u56fe\u8c31",
      entity: "\u5b9e\u4f53", relation: "\u5173\u7cfb", add_entity: "\u6dfb\u52a0\u5b9e\u4f53",
      entity_name: "\u540d\u79f0", entity_type: "\u7c7b\u578b", relation_type: "\u5173\u7cfb\u7c7b\u578b",
      doc_count: "\u6587\u6863\u6570", delete_kb: "\u786e\u8ba4\u5220\u9664\u77e5\u8bc6\u5e93", delete_kb_desc: "\u6b64\u64cd\u4f5c\u4e0d\u53ef\u64a4\u9500\u3002",
    },
    monitor: { title: "\u8d44\u6e90\u76d1\u63a7", cpu: "CPU", memory: "\u5185\u5b58", disk: "\u78c1\u76d8", gpu: "GPU", usage: "\u4f7f\u7528\u7387", total: "\u603b\u91cf", used: "\u5df2\u7528", refresh: "\u5237\u65b0" },
    data: { import: "\u5bfc\u5165\u6570\u636e", export: "\u5bfc\u51fa\u6570\u636e", batch: "\u6279\u91cf\u5bfc\u5165", format: "\u683c\u5f0f", preview: "\u9884\u89c8", label: "\u6807\u6ce8\u6570\u636e", title: "\u6570\u636e\u7ba1\u7406", upload_file: "\u4e0a\u4f20\u6587\u4ef6", filename: "\u6587\u4ef6\u540d", size: "\u5927\u5c0f", rows: "\u884c\u6570", delete_file: "\u786e\u8ba4\u5220\u9664\u6587\u4ef6", download: "\u4e0b\u8f7d" },
    automl: { title: "\u81ea\u52a8\u5316\u5efa\u6a21", run: "\u8fd0\u884c AutoML", target: "\u76ee\u6807\u5217", task: "\u4efb\u52a1\u7c7b\u578b", budget: "\u65f6\u95f4\u9884\u7b97(\u79d2)", results: "\u7ed3\u679c", best_model: "\u6700\u4f73\u6a21\u578b", score: "\u5f97\u5206", all_results: "\u6240\u6709\u7ed3\u679c", select_dataset: "\u9009\u62e9\u6570\u636e\u96c6", select_project: "\u9009\u62e9\u9879\u76ee" },
    training: { title: "\u6a21\u578b\u8bad\u7ec3", jobs: "\u8bad\u7ec3\u4efb\u52a1", status: "\u72b6\u6001", params: "\u53c2\u6570", metrics: "\u6307\u6807", operator: "\u7b97\u5b50", started: "\u5f00\u59cb\u65f6\u95f4" },
    dashboard: { title: "\u6570\u636e\u9a7e\u9a76\u8231", algorithms: "\u5185\u7f6e\u7b97\u6cd5", datasets: "\u6570\u636e\u96c6", models: "\u6a21\u578b\u603b\u6570", apis: "API\u603b\u6570", samples: "\u6837\u672c\u603b\u91cf", api_calls: "API\u8c03\u7528", projects: "\u9879\u76ee\u6570", users: "\u7528\u6237\u6570", training_jobs: "\u8bad\u7ec3\u4efb\u52a1", success_rate: "\u6210\u529f\u7387", algo_coverage: "\u7b97\u6cd5\u8986\u76d6\u5206\u5e03", model_status: "\u6a21\u578b\u72b6\u6001\u7edf\u8ba1", quick_actions: "\u5feb\u6377\u529f\u80fd", recent_projects: "\u6700\u8fd1\u9879\u76ee" },
    algorithms: { title: "\u7b97\u6cd5\u76ee\u5f55", search: "\u641c\u7d22\u7b97\u6cd5...", filter: "\u7b5b\u9009\u7c7b\u522b", category: "\u7c7b\u522b", sub_category: "\u5b50\u7c7b\u522b", framework: "\u6846\u67b6", backbone: "\u9aa8\u5e72\u7f51\u7edc", mAP: "\u57fa\u51c6mAP", speed: "\u63a8\u7406\u901f\u5ea6", tags: "\u6807\u7b7e" },
    api_market: { title: "\u7ec4\u4ef6\u5e02\u573a", all: "\u5168\u90e8", model_api: "\u6a21\u578bAPI", orch_api: "\u7f16\u6392API", custom_api: "\u81ea\u5b9a\u4e49API", version: "\u7248\u672c", status: "\u72b6\u6001", calls: "\u8c03\u7528\u6b21\u6570", rate: "\u6210\u529f\u7387", detail: "\u8be6\u60c5", test: "\u6d4b\u8bd5" },
    compute: { title: "\u8ba1\u7b97\u8d44\u6e90\u7ba1\u7406", name: "\u8282\u70b9\u540d\u79f0", ip: "IP\u5730\u5740", type: "\u7c7b\u578b", status: "\u72b6\u6001", purpose: "\u7528\u9014", cores: "CPU\u6838\u6570", gpu: "GPU\u6570", mem: "\u5185\u5b58(GB)", load: "\u8d1f\u8f7d" },
    annotations: { title: "\u6807\u6ce8\u5de5\u5177", new_task: "\u65b0\u5efa\u6807\u6ce8\u4efb\u52a1", task_name: "\u4efb\u52a1\u540d\u79f0", dataset_id: "\u6570\u636e\u96c6ID", type: "\u6807\u6ce8\u7c7b\u578b", rect: "\u77e9\u5f62\u6807\u6ce8", polygon: "\u591a\u8fb9\u5f62\u6807\u6ce8", point: "\u70b9\u6807\u6ce8", line: "\u7ebf\u6807\u6ce8", progress: "\u8fdb\u5ea6", samples: "\u6837\u672c", auto_label: "\u81ea\u52a8\u6807\u6ce8" },
    orchestration: { title: "\u591a\u667a\u80fd\u4f53\u534f\u540c", new_task: "\u65b0\u5efa\u4efb\u52a1", new_agent: "\u65b0\u589e\u667a\u80fd\u4f53", tasks: "\u534f\u540c\u4efb\u52a1", agents: "\u667a\u80fd\u4f53\u5217\u8868", planner: "\u8c03\u5ea6\u8005", llm: "\u5927\u6a21\u578b", executor: "\u6267\u884c\u8005", reviewer: "\u5ba1\u6838\u8005", priority: "\u4f18\u5148\u7ea7", requires_review: "\u9700\u5ba1\u6838", plan: "\u89c4\u5212" },
};

const en = {
    app: { title: "AI Model Training Platform", login: "Login", logout: "Logout", register: "Register" },
    nav: { dashboard: "Dashboard", projects: "Projects", models: "Models", data: "Data", users: "Users" },
    project: { create: "New Project", name: "Name", desc: "Description", list: "Projects" },
    workspace: { run: "Run", save: "Save", nodes: "Nodes", settings: "Settings", search_operator: "Search operators...", delete_workflow: "Delete Workflow", save_success: "Saved", save_failed: "Save Failed", run_failed: "Execution Failed", back: "Back", operator_panel: "Operators", run_progress: "Progress", select_node_hint: "Select a node to view properties", node_properties: "Node Properties", params_config: "Parameters", no_params: "No parameters", execution_status: "Execution Status", status: "Status:", result_preview: "Result Preview" },
    template: { welding: "Weld Quality Prediction", param_recommend: "Parameter Recommendation", anomaly_detect: "Anomaly Detection", full_ml: "Full ML Pipeline", next: "Next", create_and_run: "Create & Run" },
    operator: {
      csv_import: "CSV/Excel Import", data_table: "Data Table", data_stats: "Data Statistics",
      missing_value: "Missing Handler", label_encoder: "Encoder", scaler: "Scaler",
      train_test_split: "Train/Test Split", xgboost_train: "XGBoost Trainer", random_forest: "Random Forest",
      linear_model: "Linear Model", classification_eval: "Classification Eval", regression_eval: "Regression Eval",
      roc_curve: "ROC Curve", feature_importance: "Feature Importance", distribution: "Distribution Plot",
      mlp: "MLP Classifier", mlp_reg: "MLP Regressor", cnn1d: "1D CNN Classifier",
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
    monitor: { title: "Monitor", cpu: "CPU", memory: "Memory", disk: "Disk", gpu: "GPU", usage: "Usage", total: "Total", used: "Used", refresh: "Refresh" },
    data: { import: "Import", export: "Export", batch: "Batch Import", format: "Format", preview: "Preview", label: "Label", title: "Data Management", upload_file: "Upload File", filename: "Filename", size: "Size", rows: "Rows", delete_file: "Delete File", download: "Download" },
    automl: { title: "AutoML", run: "Run AutoML", target: "Target Column", task: "Task Type", budget: "Time Budget(s)", results: "Results", best_model: "Best Model", score: "Score", all_results: "All Results", select_dataset: "Select Dataset", select_project: "Select Project" },
    training: { title: "Training", jobs: "Jobs", status: "Status", params: "Params", metrics: "Metrics", operator: "Operator", started: "Started" },
    dashboard: { title: "Data Cockpit", algorithms: "Algorithms", datasets: "Datasets", models: "Models", apis: "APIs", samples: "Samples", api_calls: "API Calls", projects: "Projects", users: "Users", training_jobs: "Training Jobs", success_rate: "Success Rate", algo_coverage: "Algorithm Coverage", model_status: "Model Status", quick_actions: "Quick Actions", recent_projects: "Recent Projects" },
    algorithms: { title: "Algorithm Catalog", search: "Search...", filter: "Category", category: "Category", sub_category: "Sub Category", framework: "Framework", backbone: "Backbone", mAP: "mAP", speed: "Speed", tags: "Tags" },
    api_market: { title: "Marketplace", all: "All", model_api: "Model API", orch_api: "Orch. API", custom_api: "Custom API", version: "Version", status: "Status", calls: "Calls", rate: "Rate", detail: "Detail", test: "Test" },
    compute: { title: "Compute Resources", name: "Node Name", ip: "IP Address", type: "Type", status: "Status", purpose: "Purpose", cores: "CPU Cores", gpu: "GPUs", mem: "Memory(GB)", load: "Load" },
    annotations: { title: "Annotation Tool", new_task: "New Task", task_name: "Task Name", dataset_id: "Dataset ID", type: "Type", rect: "Rectangle", polygon: "Polygon", point: "Point", line: "Line", progress: "Progress", samples: "Samples", auto_label: "Auto Label" },
    orchestration: { title: "Multi-Agent", new_task: "New Task", new_agent: "New Agent", tasks: "Tasks", agents: "Agents", planner: "Planner", llm: "LLM", executor: "Executor", reviewer: "Reviewer", priority: "Priority", requires_review: "Review", plan: "Plan" },
};

const translations = { zh, en };

export type TranslationKeys = typeof en;
export const LangContext = createContext<{lang: Lang; t: TranslationKeys; setLang: (l: Lang) => void}>({
  lang: "zh", t: zh, setLang: () => {}
});
export const useI18n = () => useContext(LangContext);
export { translations };


