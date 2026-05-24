import { BrowserRouter, Routes, Route, Navigate, Outlet } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { AuthProvider, useAuth } from "@/contexts/AuthContext";
import AppShell from "@/components/layout/AppShell";
import Dashboard from "@/pages/Dashboard";
import BorrowerList from "@/pages/Borrowers/BorrowerList";
import BorrowerDetail from "@/pages/Borrowers/BorrowerDetail";
import CallList from "@/pages/Calls/CallList";
import CallDetail from "@/pages/Calls/CallDetail";
import CampaignList from "@/pages/Campaigns/CampaignList";
import CampaignDetail from "@/pages/Campaigns/CampaignDetail";
import Compliance from "@/pages/Compliance";
import CallQuality from "@/pages/CallQuality";
import HumanCallList from "@/pages/HumanCalls/HumanCallList";
import HumanCallDetail from "@/pages/HumanCalls/HumanCallDetail";
import Login from "@/pages/Auth/Login";
import Register from "@/pages/Auth/Register";
import Team from "@/pages/Settings/Team";
import ApiKeys from "@/pages/Settings/ApiKeys";
import BillingUsage from "@/pages/Billing/Usage";
import OnboardingWizard from "@/pages/Onboarding/OnboardingWizard";

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      staleTime: 15_000,
      retry: 1,
    },
  },
});

function ProtectedRoute() {
  const { isAuthenticated, isLoading } = useAuth();

  if (isLoading) {
    return (
      <div className="min-h-screen flex items-center justify-center">
        <div className="animate-spin h-8 w-8 border-4 border-blue-600 border-t-transparent rounded-full" />
      </div>
    );
  }

  if (!isAuthenticated) {
    return <Navigate to="/login" replace />;
  }

  return <Outlet />;
}

function PublicRoute() {
  const { isAuthenticated, isLoading } = useAuth();

  if (isLoading) return null;
  if (isAuthenticated) return <Navigate to="/" replace />;

  return <Outlet />;
}

export default function App() {
  return (
    <QueryClientProvider client={queryClient}>
      <AuthProvider>
        <BrowserRouter>
          <Routes>
            {/* Public routes (redirect to app if already logged in) */}
            <Route element={<PublicRoute />}>
              <Route path="/login" element={<Login />} />
              <Route path="/register" element={<Register />} />
            </Route>

            {/* Protected routes (require authentication) */}
            <Route element={<ProtectedRoute />}>
              <Route element={<AppShell />}>
                <Route path="/" element={<Dashboard />} />
                <Route path="/borrowers" element={<BorrowerList />} />
                <Route path="/borrowers/:id" element={<BorrowerDetail />} />
                <Route path="/calls" element={<CallList />} />
                <Route path="/calls/:id" element={<CallDetail />} />
                <Route path="/campaigns" element={<CampaignList />} />
                <Route path="/campaigns/:id" element={<CampaignDetail />} />
                <Route path="/compliance" element={<Compliance />} />
                <Route path="/call-quality" element={<CallQuality />} />
                <Route path="/human-calls" element={<HumanCallList />} />
                <Route path="/human-calls/:id" element={<HumanCallDetail />} />
                <Route path="/settings/team" element={<Team />} />
                <Route path="/settings/api-keys" element={<ApiKeys />} />
                <Route path="/settings/billing" element={<BillingUsage />} />
                <Route path="/onboarding" element={<OnboardingWizard />} />
              </Route>
            </Route>

            {/* Catch-all redirect */}
            <Route path="*" element={<Navigate to="/" replace />} />
          </Routes>
        </BrowserRouter>
      </AuthProvider>
    </QueryClientProvider>
  );
}
