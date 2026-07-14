# 前端测试说明

## 安装依赖

```bash
cd frontend
npm install
```

## 运行测试

```bash
npm test
```

## 测试文件

- `src/components/AppLayout.test.tsx` - 布局组件渲染测试
- `src/stores/workflowStore.test.ts` - 工作流状态管理测试（8个用例）
- `src/api/client.test.ts` - API客户端配置测试

## 添加新测试

1. 在 `src/` 目录下创建 `*.test.ts` 或 `*.test.tsx` 文件
2. 使用 vitest API: `describe`, `it`, `expect`
3. React组件测试使用 `@testing-library/react` 的 `render` 和 `screen`
