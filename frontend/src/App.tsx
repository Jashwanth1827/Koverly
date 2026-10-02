import { Navigate, Route, Routes } from "react-router-dom";
import { AppShell } from "@/components/AppShell";
import { useAuth } from "@/context/AuthContext";
import { Loading } from "@/components/ui";
import { LoginPage } from "@/pages/LoginPage";
import { OnboardingPage } from "@/pages/OnboardingPage";
import { DashboardPage } from "@/pages/DashboardPage";
import { PoliciesPage } from "@/pages/PoliciesPage";
import { PolicyDetailPage } from "@/pages/PolicyDetailPage";
import { FamilyPage } from "@/pages/FamilyPage";
import { ClaimsPage } from "@/pages/ClaimsPage";
import { ClaimDetailPage } from "@/pages/ClaimDetailPage";
import { IntelligencePage } from "@/pages/IntelligencePage";
import { DocumentsPage } from "@/pages/DocumentsPage";
import { CalendarPage } from "@/pages/CalendarPage";
import { AskPage } from "@/pages/AskPage";
import { EmergencyPage } from "@/pages/EmergencyPage";
import { EmergencySharePage } from "@/pages/EmergencySharePage";
import { SearchPage } from "@/pages/SearchPage";
import { SettingsPage } from "@/pages/SettingsPage";

function Protected({ children }: { children: React.ReactNode }) {
  const { user, loading } = useAuth();
  if (loading) return <Loading label="Loading your workspace…" />;
  if (!user) return <Navigate to="/login" replace />;
  return <>{children}</>;
}

function RequireFamily({ children }: { children: React.ReactNode }) {
  const { families, loading } = useAuth();
  if (loading) return <Loading />;
  if (families.length === 0) return <Navigate to="/onboarding" replace />;
  return <>{children}</>;
}

export function App() {
  return (
    <Routes>
      <Route path="/login" element={<LoginPage />} />
      <Route path="/emergency/share/:token" element={<EmergencySharePage />} />
      <Route
        path="/onboarding"
        element={
          <Protected>
            <OnboardingPage />
          </Protected>
        }
      />
      <Route
        element={
          <Protected>
            <RequireFamily>
              <AppShell />
            </RequireFamily>
          </Protected>
        }
      >
        <Route path="/" element={<DashboardPage />} />
        <Route path="/policies" element={<PoliciesPage />} />
        <Route path="/policies/:policyId" element={<PolicyDetailPage />} />
        <Route path="/family" element={<FamilyPage />} />
        <Route path="/claims" element={<ClaimsPage />} />
        <Route path="/claims/:claimId" element={<ClaimDetailPage />} />
        <Route path="/intelligence" element={<IntelligencePage />} />
        <Route path="/documents" element={<DocumentsPage />} />
        <Route path="/calendar" element={<CalendarPage />} />
        <Route path="/ask" element={<AskPage />} />
        <Route path="/search" element={<SearchPage />} />
        <Route path="/emergency" element={<EmergencyPage />} />
        <Route path="/settings" element={<SettingsPage />} />
      </Route>
      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  );
}
