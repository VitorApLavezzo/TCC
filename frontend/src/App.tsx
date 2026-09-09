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
import { Welcome } from "./pages/Welcome";
import { Dashboard } from "./pages/Dashboard";
import { Machines } from "./pages/Machines";
import { Anomalies } from "./pages/Anomalies";
import { AnomalyDetail } from "./pages/AnomalyDetail";
import { Account } from "./pages/Account";
import { NotFound } from "./pages/NotFound";

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
                </AuthProvider>
              </BrowserRouter>
            </ConfirmProvider>
          </ToastProvider>
        </StatusProvider>
      </ThemeProvider>
    </ErrorBoundary>
  );
}
