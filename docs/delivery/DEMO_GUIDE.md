# 焊接工业模板演示指南

## 演示数据

批准的数据源目录：

```text
C:\Users\17723\Desktop\resistance_spot_welding_dataset-main
```

目录应包含：`current.csv`、`voltage.csv`、`force.csv`、`labels.csv`。

生成特征数据：

```powershell
cd E:\codex_workspace\agent_spot_welding\ml-platform\backend
python tools\prepare_weld_demo.py `
  --source-dir "C:\Users\17723\Desktop\resistance_spot_welding_dataset-main" `
  --output ..\data\demo\weld_fault_features.csv
```

预期结果：

- 1,976 行、43 列。
- `Fault=0` 为 1,897 行，`Fault=1` 为 79 行。
- 电流、电压、压力分别生成均值、标准差、极值、中位数、范围、非零比例、峰值位置、积分等统计特征。
- 输出 JSON 包含源文件 SHA-256 和准备版本；命令不修改原始文件。

## 演示顺序

1. 使用 Windows 或 Ubuntu 脚本启动并完成健康检查。
2. 登录，创建“焊接故障演示”项目。
3. 在数据管理页上传 `weld_fault_features.csv`。
4. 打开“焊接质量预测”，选择刚上传的数据集制品并创建工作流。
5. 运行并确认 6/6 节点完成，查看分类 metrics。
6. 依次实例化其余三套模板，说明故障风险特征、异常命中率和多模型对比。
7. 展示运行详情中的节点 attempt、耗时、错误字段和结果血缘。

## 重复演示

- 每次演示创建独立项目，避免混用历史 Artifact。
- 使用相同源文件和准备版本时，输出哈希和行数应稳定。
- 四模板后端自动化测试使用全部 79 个故障样本和固定抽样的 237 个正常样本。
- Playwright 固定夹具位于 `frontend/e2e/fixtures/weld_fault_features.csv`，仅用于验收。

## 演示故障排查

- 模板列表为空：确认后端已启动并登录有效。
- 数据集下拉为空：确认上传项目与模板选择项目相同。
- `Fault` 缺失：重新执行数据准备命令，不要上传原始时序宽表。
- 节点失败：读取运行详情中的 `error_code`、`error_message` 和失败节点 attempt。
