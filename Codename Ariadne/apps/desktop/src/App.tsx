import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { lazy, Suspense } from 'react'
import { BrowserRouter, Navigate, Route, Routes } from 'react-router-dom'
import { AppShell } from './components/AppShell'

const DashboardPage = lazy(() =>
  import('./pages/DashboardPage').then((module) => ({
    default: module.DashboardPage,
  })),
)
const NewAuditPage = lazy(() =>
  import('./pages/NewAuditPage').then((module) => ({
    default: module.NewAuditPage,
  })),
)
const IntakePage = lazy(() =>
  import('./pages/IntakePage').then((module) => ({
    default: module.IntakePage,
  })),
)
const EntitiesPage = lazy(() =>
  import('./pages/EntitiesPage').then((module) => ({
    default: module.EntitiesPage,
  })),
)
const PeoplePage = lazy(() =>
  import('./pages/PeoplePage').then((module) => ({
    default: module.PeoplePage,
  })),
)
const IdentityAuditPage = lazy(() =>
  import('./pages/IdentityAuditPage').then((module) => ({
    default: module.IdentityAuditPage,
  })),
)
const ToolsPage = lazy(() =>
  import('./pages/ToolsPage').then((module) => ({
    default: module.ToolsPage,
  })),
)
const AIWorkspacePage = lazy(() =>
  import('./pages/AIWorkspacePage').then((module) => ({
    default: module.AIWorkspacePage,
  })),
)
const CorpusAIPage = lazy(() =>
  import('./pages/CorpusAIPage').then((module) => ({
    default: module.CorpusAIPage,
  })),
)
const OperationsPage = lazy(() =>
  import('./pages/OperationsPage').then((module) => ({
    default: module.OperationsPage,
  })),
)
const FindingsPage = lazy(() =>
  import('./pages/FindingsPage').then((module) => ({
    default: module.FindingsPage,
  })),
)
const FindingDetailPage = lazy(() =>
  import('./pages/FindingDetailPage').then((module) => ({
    default: module.FindingDetailPage,
  })),
)
const GraphPage = lazy(() =>
  import('./pages/GraphPage').then((module) => ({
    default: module.GraphPage,
  })),
)
const MapPage = lazy(() =>
  import('./pages/MapPage').then((module) => ({
    default: module.MapPage,
  })),
)
const ImpersonationPage = lazy(() =>
  import('./pages/ImpersonationPage').then((module) => ({
    default: module.ImpersonationPage,
  })),
)
const ComparePage = lazy(() =>
  import('./pages/ComparePage').then((module) => ({
    default: module.ComparePage,
  })),
)
const RemediationPage = lazy(() =>
  import('./pages/RemediationPage').then((module) => ({
    default: module.RemediationPage,
  })),
)
const ReportsPage = lazy(() =>
  import('./pages/ReportsPage').then((module) => ({
    default: module.ReportsPage,
  })),
)
const ProvidersPage = lazy(() =>
  import('./pages/ProvidersPage').then((module) => ({
    default: module.ProvidersPage,
  })),
)
const TransmissionPage = lazy(() =>
  import('./pages/TransmissionPage').then((module) => ({
    default: module.TransmissionPage,
  })),
)
const SettingsPage = lazy(() =>
  import('./pages/SettingsPage').then((module) => ({
    default: module.SettingsPage,
  })),
)
const StatesPage = lazy(() =>
  import('./pages/StatesPage').then((module) => ({
    default: module.StatesPage,
  })),
)
const GettingStartedPage = lazy(() =>
  import('./pages/GettingStartedPage').then((module) => ({
    default: module.GettingStartedPage,
  })),
)

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      retry: false,
      staleTime: Number.POSITIVE_INFINITY,
    },
  },
})

function RoutedApp() {
  return (
    <AppShell>
      <Suspense
        fallback={
          <div className="page" aria-busy="true" aria-live="polite">
            <h1 id="page-title" tabIndex={-1}>
              Loading local workspace
            </h1>
          </div>
        }
      >
        <Routes>
          <Route path="/" element={<Navigate replace to="/dashboard" />} />
          <Route path="/dashboard" element={<DashboardPage />} />
          <Route path="/audits/new" element={<NewAuditPage />} />
          <Route path="/audits/new/intake" element={<IntakePage />} />
          <Route path="/audits/new/entities" element={<EntitiesPage />} />
          <Route path="/people" element={<PeoplePage />} />
          <Route path="/identity/audits/:auditId" element={<IdentityAuditPage />} />
          <Route path="/tools" element={<ToolsPage />} />
          <Route path="/ai/workspace" element={<AIWorkspacePage />} />
          <Route path="/ai/corpus" element={<CorpusAIPage />} />
          <Route path="/operations/:runId" element={<OperationsPage />} />
          <Route path="/findings" element={<FindingsPage />} />
          <Route path="/findings/:findingId" element={<FindingDetailPage />} />
          <Route path="/graph" element={<GraphPage />} />
          <Route path="/map" element={<MapPage />} />
          <Route
            path="/cases/impersonation/:caseId"
            element={<ImpersonationPage />}
          />
          <Route path="/compare" element={<ComparePage />} />
          <Route path="/remediation" element={<RemediationPage />} />
          <Route path="/reports" element={<ReportsPage />} />
          <Route path="/providers" element={<ProvidersPage />} />
          <Route
            path="/privacy/transmission"
            element={<TransmissionPage />}
          />
          <Route path="/settings/privacy" element={<SettingsPage />} />
          <Route
            path="/help/getting-started"
            element={<GettingStartedPage />}
          />
          <Route path="/states" element={<StatesPage />} />
          <Route path="*" element={<Navigate replace to="/dashboard" />} />
        </Routes>
      </Suspense>
    </AppShell>
  )
}

export default function App() {
  return (
    <QueryClientProvider client={queryClient}>
      <BrowserRouter>
        <RoutedApp />
      </BrowserRouter>
    </QueryClientProvider>
  )
}
