# 前端测试说明

## 安装依赖

```bash
cd ml-platform/frontend
npm ci
```

## 运行测试

```bash
npm test
```

## 测试文件

- 第一周：认证与 API 客户端、应用布局、生产模块导入、知识库、知识图谱、用户管理、主题和测试清单自检。
- 第二周：工作流版本、工作区端口持久化、工作流 Store。
- 第三周：训练 API、训练任务页面和数据管理。
- 第四周：工业模板 API、节点、配置面板、Join 键对、算子面板与模板向导。
- 第六周：实验 API 和 AutoML 页面。
- 第八周：模型注册 API 和模型库页面。

`src/weekAcceptance.test.ts` 维护完整映射并保证每个测试文件只归属一个周次。当前基线为 27 个测试文件、64 个测试。

生产构建和浏览器验收：

```bash
npm run build
npx playwright test --project=chromium
```

## 添加新测试

1. 在 `src/` 目录下创建 `*.test.ts` 或 `*.test.tsx` 文件
2. 使用 vitest API: `describe`, `it`, `expect`
3. React 组件测试使用 `@testing-library/react` 的 `render` 和 `screen`
4. 将新测试文件加入 `src/weekAcceptance.test.ts` 对应周次
5. 提交前执行 `npm test`，确保清单自检和全部用例通过
