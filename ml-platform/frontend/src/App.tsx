import { BrowserRouter, Routes, Route, Navigate } from "react-router-dom";
import { ConfigProvider, theme as antTheme, App as AntApp } from "antd";
import { useTheme } from "./stores/themeContext";
import ProtectedRoute from "./components/ProtectedRoute";
import LoginPage from "./pages/LoginPage";
import RegisterPage from "./pages/RegisterPage";
import DashboardPage from "./pages/DashboardPage";
import ProjectListPage from "./pages/ProjectListPage";
import ProjectDetailPage from "./pages/ProjectDetailPage";
import WorkspacePage from "./pages/WorkspacePage";
import TemplateWizardPage from "./pages/TemplateWizardPage";
import ModelLibraryPage from "./pages/ModelLibraryPage";
import DataManagePage from "./pages/DataManagePage";
import UserManagementPage from "./pages/UserManagementPage";
import KnowledgeBasePage from "./pages/KnowledgeBasePage";
import KnowledgeDetailPage from "./pages/KnowledgeDetailPage";
import KnowledgeGraphPage from "./pages/KnowledgeGraphPage";
import AutoMLPage from "./pages/AutoMLPage";
import TrainingJobsPage from "./pages/TrainingJobsPage";
import MonitorPage from "./pages/MonitorPage";
import AlgorithmCatalogPage from "./pages/AlgorithmCatalogPage";
import APIMarketplacePage from "./pages/APIMarketplacePage";
import AnnotationPage from "./pages/AnnotationPage";
import OrchestrationPage from "./pages/OrchestrationPage";
import ComputeResourcePage from "./pages/ComputeResourcePage";
import AIChatPage from "./pages/AIChatPage";

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
      </AntApp>
    </ConfigProvider>
  );
}

export default function App() {
  return <AppContent />;
}