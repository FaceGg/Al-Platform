import { BrowserRouter, Routes, Route, Navigate } from "react-router-dom";
import { lazy, Suspense } from "react";
import { ConfigProvider, theme as antTheme, App as AntApp, Spin } from "antd";
import { useTheme } from "./stores/themeContext";
import ProtectedRoute from "./components/ProtectedRoute";
import PageErrorBoundary from "./components/PageErrorBoundary";

const LoginPage = lazy(() => import("./pages/LoginPage"));
const RegisterPage = lazy(() => import("./pages/RegisterPage"));
const DashboardPage = lazy(() => import("./pages/DashboardPage"));
const ProjectListPage = lazy(() => import("./pages/ProjectListPage"));
const ProjectDetailPage = lazy(() => import("./pages/ProjectDetailPage"));
const WorkspacePage = lazy(() => import("./pages/WorkspacePage"));
const TemplateWizardPage = lazy(() => import("./pages/TemplateWizardPage"));
const ModelLibraryPage = lazy(() => import("./pages/ModelLibraryPage"));
const DataManagePage = lazy(() => import("./pages/DataManagePage"));
const UserManagementPage = lazy(() => import("./pages/UserManagementPage"));
const KnowledgeBasePage = lazy(() => import("./pages/KnowledgeBasePage"));
const KnowledgeDetailPage = lazy(() => import("./pages/KnowledgeDetailPage"));
const KnowledgeGraphPage = lazy(() => import("./pages/KnowledgeGraphPage"));
const AutoMLPage = lazy(() => import("./pages/AutoMLPage"));
const AutoMLTaskPage = lazy(() => import("./pages/AutoMLTaskPage"));
const TrainingJobsPage = lazy(() => import("./pages/TrainingJobsPage"));
const MonitorPage = lazy(() => import("./pages/MonitorPage"));
const AlgorithmCatalogPage = lazy(() => import("./pages/AlgorithmCatalogPage"));
const APIMarketplacePage = lazy(() => import("./pages/APIMarketplacePage"));
const AnnotationPage = lazy(() => import("./pages/AnnotationPage"));
const DataAnnotationPage = lazy(() => import("./pages/DataAnnotationPage"));
const OrchestrationPage = lazy(() => import("./pages/OrchestrationPage"));
const ComputeResourcePage = lazy(() => import("./pages/ComputeResourcePage"));
const AIChatPage = lazy(() => import("./pages/AIChatPage"));

const LIGHT_TOKENS = {
  colorPrimary: "#2F9BF5",
  colorSuccess: "#47C3A0",
  colorWarning: "#D9AC52",
  colorError: "#E66F75",
  colorInfo: "#2F9BF5",
  borderRadius: 14,
  borderRadiusLG: 20,
  fontFamily: "-apple-system, BlinkMacSystemFont, 'Segoe UI', 'PingFang SC', 'Microsoft YaHei', 'Helvetica Neue', sans-serif",
  colorBgContainer: "#FFFFFF",
  colorBgLayout: "#EDF5F7",
  colorBgElevated: "#F5FAFB",
  colorBorder: "rgba(45, 102, 119, 0.18)",
  colorText: "#142A33",
  colorTextSecondary: "#57707B",
};

const DARK_TOKENS = {
  colorPrimary: "#2F9BF5",
  colorSuccess: "#47C3A0",
  colorWarning: "#D9AC52",
  colorError: "#E66F75",
  colorInfo: "#2F9BF5",
  borderRadius: 14,
  borderRadiusLG: 20,
  fontFamily: "-apple-system, BlinkMacSystemFont, 'Segoe UI', 'PingFang SC', 'Microsoft YaHei', 'Helvetica Neue', sans-serif",
  colorBgContainer: "#10222C",
  colorBgLayout: "#0C151C",
  colorBgElevated: "#152C38",
  colorBorder: "rgba(147, 190, 207, 0.20)",
  colorText: "#EDF6FA",
  colorTextSecondary: "#9BB2BF",
};

function AppContent() {
  const { theme } = useTheme();
  const isDark = theme === "dark";

  return (
    <ConfigProvider
      theme={{
        algorithm: isDark ? antTheme.darkAlgorithm : antTheme.defaultAlgorithm,
        token: isDark ? DARK_TOKENS : LIGHT_TOKENS,
      }}
    >
      <AntApp>
        <Suspense fallback={<div style={{ display: "grid", minHeight: "100vh", placeItems: "center" }}><Spin size="large" /></div>}>
          <BrowserRouter>
            <Routes>
            <Route path="/login" element={<LoginPage />} />
            <Route path="/register" element={<RegisterPage />} />
            <Route path="/" element={<ProtectedRoute><DashboardPage /></ProtectedRoute>} />
            <Route path="/projects" element={<ProtectedRoute><ProjectListPage /></ProtectedRoute>} />
            <Route path="/projects/:projectId" element={<ProtectedRoute><ProjectDetailPage /></ProtectedRoute>} />
            <Route path="/workspace/:workflowId" element={<ProtectedRoute><WorkspacePage /></ProtectedRoute>} />
            <Route path="/template/:templateId" element={<ProtectedRoute><TemplateWizardPage /></ProtectedRoute>} />
            <Route path="/models" element={<ProtectedRoute><ModelLibraryPage /></ProtectedRoute>} />
            <Route path="/data" element={<ProtectedRoute><DataManagePage /></ProtectedRoute>} />
            <Route path="/admin/users" element={<ProtectedRoute><UserManagementPage /></ProtectedRoute>} />
            <Route path="/knowledge" element={<ProtectedRoute><KnowledgeBasePage /></ProtectedRoute>} />
            <Route path="/knowledge/:kbId" element={<ProtectedRoute><KnowledgeDetailPage /></ProtectedRoute>} />
            <Route path="/knowledge-graph" element={<ProtectedRoute><KnowledgeGraphPage /></ProtectedRoute>} />
            <Route path="/automl" element={<ProtectedRoute><PageErrorBoundary pageName="自动建模"><AutoMLPage /></PageErrorBoundary></ProtectedRoute>} />
            <Route path="/automl/task/:taskId" element={<ProtectedRoute><PageErrorBoundary pageName="自动建模任务"><AutoMLTaskPage /></PageErrorBoundary></ProtectedRoute>} />
            <Route path="/training" element={<ProtectedRoute><TrainingJobsPage /></ProtectedRoute>} />
            <Route path="/monitor" element={<ProtectedRoute><MonitorPage /></ProtectedRoute>} />
            <Route path="/algorithms" element={<ProtectedRoute><AlgorithmCatalogPage /></ProtectedRoute>} />
            <Route path="/api-marketplace" element={<ProtectedRoute><APIMarketplacePage /></ProtectedRoute>} />
            <Route path="/annotations" element={<ProtectedRoute><AnnotationPage /></ProtectedRoute>} />
            <Route path="/data-annotation" element={<ProtectedRoute><DataAnnotationPage /></ProtectedRoute>} />
            <Route path="/orchestration" element={<ProtectedRoute><OrchestrationPage /></ProtectedRoute>} />
            <Route path="/compute" element={<ProtectedRoute><ComputeResourcePage /></ProtectedRoute>} />
            <Route path="/chat" element={<ProtectedRoute><AIChatPage /></ProtectedRoute>} />
            <Route path="*" element={<Navigate to="/" replace />} />
            </Routes>
          </BrowserRouter>
        </Suspense>
      </AntApp>
    </ConfigProvider>
  );
}

export default function App() {
  return <AppContent />;
}
