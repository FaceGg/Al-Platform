import { useState, useCallback } from "react";
import { BrowserRouter, Routes, Route, Navigate } from "react-router-dom";
import { ConfigProvider } from "antd";
import zhCN from "antd/locale/zh_CN";
import enUS from "antd/locale/en_US";
import { LangContext, translations, type TranslationKeys } from "./i18n";
import LoginPage from "./pages/LoginPage";
import RegisterPage from "./pages/RegisterPage";
import DashboardPage from "./pages/DashboardPage";
import ProjectListPage from "./pages/ProjectListPage";
import ProjectDetailPage from "./pages/ProjectDetailPage";
import WorkspacePage from "./pages/WorkspacePage";
import TemplateWizardPage from "./pages/TemplateWizardPage";
import ModelLibraryPage from "./pages/ModelLibraryPage";
import UserManagementPage from "./pages/UserManagementPage";
import KnowledgeBasePage from "./pages/KnowledgeBasePage";
import KnowledgeDetailPage from "./pages/KnowledgeDetailPage";
import KnowledgeGraphPage from "./pages/KnowledgeGraphPage";
import DataManagePage from "./pages/DataManagePage";
import AutoMLPage from "./pages/AutoMLPage";
import TrainingJobsPage from "./pages/TrainingJobsPage";
import MonitorPage from "./pages/MonitorPage";
import ProtectedRoute from "./components/ProtectedRoute";

type Lang = "zh" | "en";

export default function App() {
  const [lang, setLangState] = useState<Lang>(() => (localStorage.getItem("lang") as Lang) || "zh");
  const setLang = useCallback((l: Lang) => {
    setLangState(l);
    localStorage.setItem("lang", l);
  }, []);
  const t: TranslationKeys = translations[lang];
  const locale = lang === "zh" ? zhCN : enUS;

  return (
    <LangContext.Provider value={{ lang, t, setLang }}>
      <ConfigProvider locale={locale}>
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
            <Route path="*" element={<Navigate to="/" replace />} />
          </Routes>
        </BrowserRouter>
      </ConfigProvider>
    </LangContext.Provider>
  );
}
