import { Suspense, lazy } from "react";
import { BrowserRouter, Routes, Route, Navigate } from "react-router-dom";
import { AuthProvider, useAuth } from "./context/AuthContext";
import { StatusProvider } from "./context/StatusContext";
import { ThemeProvider } from "./context/ThemeContext";
import { ToastProvider } from "./components/ui/Toast";
import { ConfirmProvider } from "./components/ui/ConfirmDialog";
import { ErrorBoundary } from "./components/ErrorBoundary";
import { AppShell } from "./components/AppShell";
import { Login } from "./pages/Login";
import { Register } from "./pages/Register";
const Welcome = lazy(() => import("./pages/Welcome").then((m) => ({ default: m.Welcome })));
const Dashboard = lazy(() => import("./pages/Dashboard").then((m) => ({ default: m.Dashboard })));
const Machines = lazy(() => import("./pages/Machines").then((m) => ({ default: m.Machines })));
const MachineDetail = lazy(() => import("./pages/MachineDetail").then((m) => ({ default: m.MachineDetail })));
const Anomalies = lazy(() => import("./pages/Anomalies").then((m) => ({ default: m.Anomalies })));
const AnomalyDetail = lazy(() => import("./pages/AnomalyDetail").then((m) => ({ default: m.AnomalyDetail })));
const Chat = lazy(() => import("./pages/Chat").then((m) => ({ default: m.Chat })));
const Demo = lazy(() => import("./pages/Demo").then((m) => ({ default: m.Demo })));
const Research = lazy(() => import("./pages/Research").then((m) => ({ default: m.Research })));
const Study = lazy(() => import("./pages/Study").then((m) => ({ default: m.Study })));
const SharedView = lazy(() => import("./pages/SharedView").then((m) => ({ default: m.SharedView })));
const Account = lazy(() => import("./pages/Account").then((m) => ({ default: m.Account })));
import { NotFound } from "./pages/NotFound";

/** Enquanto o pedaço da página chega da rede. */
function PageFallback() {
  return (
    <div className="flex min-h-[40vh] items-center justify-center">
      <div
        role="status"
        aria-label="Carregando"
        className="h-6 w-6 animate-spin rounded-full border-2 border-edge border-t-fg"
      />
    </div>
  );
}

function PrivateRoute({ children }: { children: React.ReactNode }) {
  const { user, loading } = useAuth();
  if (loading) {
    return (
      <div className="flex min-h-screen items-center justify-center bg-canvas">
        <div
          role="status"
          aria-label="Carregando"
          className="h-6 w-6 animate-spin rounded-full border-2 border-edge border-t-fg"
        />
      </div>
    );
  }
  return user ? <AppShell>{children}</AppShell> : <Navigate to="/login" replace />;
}

function PublicRoute({ children }: { children: React.ReactNode }) {
  const { user, loading } = useAuth();
  if (loading) return null;
  return user ? <Navigate to="/" replace /> : <>{children}</>;
}

export default function App() {
  return (
    <ErrorBoundary>
      <ThemeProvider>
        <StatusProvider>
          <ToastProvider>
            <ConfirmProvider>
              <BrowserRouter>
                <AuthProvider>
                  <Suspense fallback={<PageFallback />}>
                  <Routes>
                    <Route
                      path="/login"
                      element={
                        <PublicRoute>
                          <Login />
                        </PublicRoute>
                      }
                    />
                    <Route
                      path="/register"
                      element={
                        <PublicRoute>
                          <Register />
                        </PublicRoute>
                      }
                    />
                    {/* Página pública do link para o técnico — sem login. */}
                    <Route path="/compartilhado/:token" element={<SharedView />} />
                    <Route
                      path="/"
                      element={
                        <PrivateRoute>
                          <Dashboard />
                        </PrivateRoute>
                      }
                    />
                    <Route
                      path="/welcome"
                      element={
                        <PrivateRoute>
                          <Welcome />
                        </PrivateRoute>
                      }
                    />
                    <Route
                      path="/machines"
                      element={
                        <PrivateRoute>
                          <Machines />
                        </PrivateRoute>
                      }
                    />
                    <Route
                      path="/machines/:id"
                      element={
                        <PrivateRoute>
                          <MachineDetail />
                        </PrivateRoute>
                      }
                    />
                    <Route
                      path="/pergunte"
                      element={
                        <PrivateRoute>
                          <Chat />
                        </PrivateRoute>
                      }
                    />
                    <Route
                      path="/demonstracao"
                      element={
                        <PrivateRoute>
                          <Demo />
                        </PrivateRoute>
                      }
                    />
                    <Route
                      path="/pesquisa"
                      element={
                        <PrivateRoute>
                          <Research />
                        </PrivateRoute>
                      }
                    />
                    <Route
                      path="/estudo"
                      element={
                        <PrivateRoute>
                          <Study />
                        </PrivateRoute>
                      }
                    />
                    <Route
                      path="/anomalies"
                      element={
                        <PrivateRoute>
                          <Anomalies />
                        </PrivateRoute>
                      }
                    />
                    <Route
                      path="/anomalies/:id"
                      element={
                        <PrivateRoute>
                          <AnomalyDetail />
                        </PrivateRoute>
                      }
                    />
                    <Route
                      path="/account"
                      element={
                        <PrivateRoute>
                          <Account />
                        </PrivateRoute>
                      }
                    />
                    {/* Endereço desconhecido mostra uma página, em vez de
                        redirecionar em silêncio para o painel. */}
                    <Route
                      path="*"
                      element={
                        <PrivateRoute>
                          <NotFound />
                        </PrivateRoute>
                      }
                    />
                  </Routes>
                  </Suspense>
                </AuthProvider>
              </BrowserRouter>
            </ConfirmProvider>
          </ToastProvider>
        </StatusProvider>
      </ThemeProvider>
    </ErrorBoundary>
  );
}
