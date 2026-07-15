import { BrowserRouter, Routes, Route, Navigate } from "react-router-dom";
import { lazy, Suspense } from "react";
import { ConfigProvider, theme as antTheme, App as AntApp, Spin } from "antd";
import { useTheme } from "./stores/themeContext";
import ProtectedRoute from "./components/ProtectedRoute";

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
const TrainingJobsPage = lazy(() => import("./pages/TrainingJobsPage"));
const MonitorPage = lazy(() => import("./pages/MonitorPage"));
const AlgorithmCatalogPage = lazy(() => import("./pages/AlgorithmCatalogPage"));
const APIMarketplacePage = lazy(() => import("./pages/APIMarketplacePage"));
const AnnotationPage = lazy(() => import("./pages/AnnotationPage"));
const OrchestrationPage = lazy(() => import("./pages/OrchestrationPage"));
const ComputeResourcePage = lazy(() => import("./pages/ComputeResourcePage"));
const AIChatPage = lazy(() => import("./pages/AIChatPage"));

const LIGHT_TOKENS = {
  colorPrimary: "#F0883E",
  colorSuccess: "#3FB950",
  colorWarning: "#D29922",
  colorError: "#F85149",
  colorInfo: "#58A6FF",
  borderRadius: 8,
  fontFamily: "-apple-system, BlinkMacSystemFont, 'Segoe UI', 'PingFang SC', 'Microsoft YaHei', 'Helvetica Neue', sans-serif",
  colorBgContainer: "#FFFFFF",
  colorBgElevated: "#F8F9FA",
  colorBorder: "#E1E4E8",
  colorText: "#24292F",
  colorTextSecondary: "#57606A",
};

const DARK_TOKENS = {
  colorPrimary: "#F0883E",
  colorSuccess: "#3FB950",
  colorWarning: "#D29922",
  colorError: "#F85149",
  colorInfo: "#58A6FF",
  borderRadius: 8,
  fontFamily: "-apple-system, BlinkMacSystemFont, 'Segoe UI', 'PingFang SC', 'Microsoft YaHei', 'Helvetica Neue', sans-serif",
  colorBgContainer: "#161B22",
  colorBgElevated: "#1C2129",
  colorBorder: "#30363D",
  colorText: "#E6EDF3",
  colorTextSecondary: "#8B949E",
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
          <BrowserRouter future={{ v7_startTransition: true, v7_relativeSplatPath: true }}>
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
            <Route path="/automl" element={<ProtectedRoute><AutoMLPage /></ProtectedRoute>} />
            <Route path="/training" element={<ProtectedRoute><TrainingJobsPage /></ProtectedRoute>} />
            <Route path="/monitor" element={<ProtectedRoute><MonitorPage /></ProtectedRoute>} />
            <Route path="/algorithms" element={<ProtectedRoute><AlgorithmCatalogPage /></ProtectedRoute>} />
            <Route path="/api-marketplace" element={<ProtectedRoute><APIMarketplacePage /></ProtectedRoute>} />
            <Route path="/annotations" element={<ProtectedRoute><AnnotationPage /></ProtectedRoute>} />
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
