import { ReactNode, useCallback, useEffect, useState } from "react";
import { Link, useLocation, useNavigate } from "react-router-dom";
import { clsx } from "clsx";
import { Menu, X, Sun, Moon } from "lucide-react";
import { useAuth } from "../context/AuthContext";
import { useStatus } from "../context/StatusContext";
import { useTheme } from "../context/ThemeContext";
import { anomaliesApi } from "../services/api";
import { usePolling } from "../hooks/usePolling";
import { StatusDot } from "./ui/Layout";

const NAV = [
  { to: "/", label: "Painel" },
  { to: "/machines", label: "Computadores" },
  { to: "/anomalies", label: "Avisos" },
];

/**
 * Shell da aplicação: navegação lateral no desktop, gaveta no celular.
 *
 * A versão anterior fixava `w-60` e `ml-60` sem nenhum breakpoint — no celular
 * a barra cobria um terço da tela e não fechava. A navegação também perdeu os
 * ícones: três itens com nomes claros não precisam de reforço pictórico, e os
 * ícones só somavam ruído numa coluna estreita.
 */
export function AppShell({ children }: { children: ReactNode }) {
  const { user, logout } = useAuth();
  const { reachable } = useStatus();
  const { theme, toggle } = useTheme();
  const location = useLocation();
  const navigate = useNavigate();
  const [drawerOpen, setDrawerOpen] = useState(false);
  const [pending, setPending] = useState(0);

  // Contador de avisos em aberto: sem ele, uma anomalia surgindo enquanto a
  // pessoa está em outra página não deixava rastro nenhum.
  const fetchPending = useCallback(async () => {
    const res = await anomaliesApi.list({ hours: 168, unresolved_only: true });
    setPending(res.data.length);
  }, []);
  usePolling(fetchPending, 45000);

  useEffect(() => setDrawerOpen(false), [location.pathname]);
  useEffect(() => {
    if (!drawerOpen) return;
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && setDrawerOpen(false);
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [drawerOpen]);

  const handleLogout = () => {
    logout();
    navigate("/login");
  };

  const nav = (
    <>
      <div className="flex h-14 flex-shrink-0 items-center gap-2 border-b border-hairline px-4">
        <span className="h-4 w-1 rounded-full bg-fg" aria-hidden="true" />
        <span className="text-sm font-semibold tracking-tight text-fg">AnomalyDetect</span>
      </div>

      <nav aria-label="Seções" className="flex-1 px-2 py-3">
        {NAV.map(({ to, label }) => {
          const active = to === "/" ? location.pathname === "/" : location.pathname.startsWith(to);
          const badge = to === "/anomalies" && pending > 0 ? pending : null;
          return (
            <Link
              key={to}
              to={to}
              aria-current={active ? "page" : undefined}
              className={clsx(
                "relative flex items-center justify-between gap-2 rounded-control px-3 py-1.5 text-sm transition-colors",
                active ? "bg-sunken font-medium text-fg" : "text-fg-2 hover:bg-sunken hover:text-fg"
              )}
            >
              {/* Marcador de seleção: uma barra, não um bloco colorido. */}
              {active && (
                <span
                  className="absolute inset-y-1.5 left-0 w-0.5 rounded-full bg-accent"
                  aria-hidden="true"
                />
              )}
              <span>{label}</span>
              {badge !== null && (
                <span className="tnum text-xs text-fg-3" aria-label={`${badge} em aberto`}>
                  {badge > 99 ? "99+" : badge}
                </span>
              )}
            </Link>
          );
        })}
      </nav>

      <div className="flex-shrink-0 border-t border-hairline p-2">
        {reachable === false && (
          <p className="mb-1 flex items-center gap-2 px-3 py-1.5 text-xs text-warn">
            <StatusDot tone="warn" />
            Servidor fora de contato
          </p>
        )}
        <Link
          to="/account"
          className={clsx(
            "flex items-center gap-2.5 rounded-control px-3 py-2 transition-colors hover:bg-sunken",
            location.pathname === "/account" && "bg-sunken"
          )}
        >
          <span className="flex h-6 w-6 flex-shrink-0 items-center justify-center rounded-full bg-sunken text-micro font-semibold text-fg-2">
            {user?.username?.[0]?.toUpperCase()}
          </span>
          <span className="min-w-0 flex-1">
            <span className="block truncate text-xs font-medium text-fg">{user?.username}</span>
            <span className="block truncate text-micro text-fg-3">{user?.email}</span>
          </span>
        </Link>
        <div className="mt-1 flex items-center gap-1">
          <button
            type="button"
            onClick={toggle}
            aria-label={theme === "dark" ? "Usar o tema claro" : "Usar o tema escuro"}
            className="flex h-7 w-7 items-center justify-center rounded-control text-fg-3 transition-colors hover:bg-sunken hover:text-fg"
          >
            {theme === "dark" ? <Sun size={14} aria-hidden="true" /> : <Moon size={14} aria-hidden="true" />}
          </button>
          <button
            type="button"
            onClick={handleLogout}
            className="flex-1 rounded-control px-2 py-1.5 text-left text-xs text-fg-3 transition-colors hover:bg-sunken hover:text-fg"
          >
            Sair da conta
          </button>
        </div>
      </div>
    </>
  );

  return (
    <div className="min-h-screen bg-canvas">
      <a
        href="#conteudo"
        className="sr-only focus:not-sr-only focus:absolute focus:left-4 focus:top-4 focus:z-50 focus:rounded-control focus:bg-inverse focus:px-3 focus:py-2 focus:text-sm focus:font-medium focus:text-inverse-fg"
      >
        Ir para o conteúdo
      </a>

      <header className="sticky top-0 z-30 flex h-14 items-center gap-3 border-b border-hairline bg-canvas px-3 lg:hidden">
        <button
          type="button"
          onClick={() => setDrawerOpen(true)}
          aria-label="Abrir o menu"
          aria-expanded={drawerOpen}
          className="flex h-8 w-8 items-center justify-center rounded-control text-fg-2 hover:bg-sunken hover:text-fg"
        >
          <Menu size={17} aria-hidden="true" />
        </button>
        <span className="text-sm font-semibold tracking-tight text-fg">AnomalyDetect</span>
        {pending > 0 && (
          <span className="tnum ml-auto text-xs text-fg-2">
            {pending} {pending === 1 ? "aviso" : "avisos"}
          </span>
        )}
      </header>

      {drawerOpen && (
        <div className="fixed inset-0 z-40 lg:hidden">
          <div className="absolute inset-0 bg-black/50" onClick={() => setDrawerOpen(false)} aria-hidden="true" />
          <div
            role="dialog"
            aria-modal="true"
            aria-label="Menu"
            className="absolute inset-y-0 left-0 flex w-64 max-w-[82vw] flex-col border-r border-hairline bg-surface shadow-float"
          >
            <button
              type="button"
              onClick={() => setDrawerOpen(false)}
              aria-label="Fechar o menu"
              className="absolute right-2 top-3 flex h-8 w-8 items-center justify-center rounded-control text-fg-3 hover:bg-sunken hover:text-fg"
            >
              <X size={16} aria-hidden="true" />
            </button>
            {nav}
          </div>
        </div>
      )}

      <aside className="fixed inset-y-0 left-0 z-20 hidden w-56 flex-col border-r border-hairline bg-surface lg:flex">
        {nav}
      </aside>

      <main id="conteudo" className="lg:pl-56">
        <div className="mx-auto max-w-5xl space-y-8 px-4 py-6 sm:px-8 sm:py-8">{children}</div>
      </main>
    </div>
  );
}
