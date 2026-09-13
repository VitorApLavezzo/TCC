import { ReactNode, useCallback, useState } from "react";
import { Link, useLocation, useNavigate } from "react-router-dom";
import { clsx } from "clsx";
import { Sun, Moon, LayoutGrid, Monitor, Bell, MessageSquare, FlaskConical } from "lucide-react";
import { useAuth } from "../context/AuthContext";
import { useStatus } from "../context/StatusContext";
import { useTheme } from "../context/ThemeContext";
import { anomaliesApi } from "../services/api";
import { usePolling } from "../hooks/usePolling";
import { StatusDot } from "./ui/Layout";
import { SignalMark } from "./ui/SignalMark";
import { NotificationsBell } from "./NotificationsBell";

const NAV = [
  { to: "/", label: "Painel", icon: LayoutGrid },
  { to: "/machines", label: "Computadores", icon: Monitor },
  { to: "/anomalies", label: "Avisos", icon: Bell },
  { to: "/pergunte", label: "Pergunte", icon: MessageSquare },
  { to: "/pesquisa", label: "Pesquisa", icon: FlaskConical },
];

/**
 * Shell da aplicação: navegação lateral de 232px no desktop, barra inferior
 * fixa no celular/tablet. O item ativo acende com fundo accent suave e ícone
 * em accent — a mesma linguagem do resto do produto.
 */
export function AppShell({ children }: { children: ReactNode }) {
  const { user, logout } = useAuth();
  const { reachable } = useStatus();
  const { theme, toggle } = useTheme();
  const location = useLocation();
  const navigate = useNavigate();
  const [pending, setPending] = useState(0);

  // Contador de avisos em aberto: sem ele, uma anomalia surgindo enquanto a
  // pessoa está em outra página não deixava rastro nenhum.
  const fetchPending = useCallback(async () => {
    const res = await anomaliesApi.list({ hours: 168, unresolved_only: true });
    setPending(res.data.length);
  }, []);
  usePolling(fetchPending, 45000);

  const handleLogout = () => {
    logout();
    navigate("/login");
  };

  const isActive = (to: string) => (to === "/" ? location.pathname === "/" : location.pathname.startsWith(to));

  return (
    <div className="min-h-screen bg-canvas">
      <a
        href="#conteudo"
        className="sr-only focus:not-sr-only focus:absolute focus:left-4 focus:top-4 focus:z-50 focus:rounded-control focus:bg-accent focus:px-3 focus:py-2 focus:text-sm focus:font-medium focus:text-canvas"
      >
        Ir para o conteúdo
      </a>

      {/* Cabeçalho compacto: abaixo de lg, quando a lateral vira barra inferior. */}
      <header className="sticky top-0 z-30 flex h-14 items-center gap-3 border-b border-hairline bg-surface px-4 lg:hidden">
        <SignalMark />
        <span className="font-display text-sm font-semibold tracking-tight text-fg">AnomalyDetect</span>
        {pending > 0 && (
          <span className="tnum ml-1 rounded-full bg-warn/15 px-2 py-0.5 font-mono text-micro font-medium text-warn">
            {pending > 99 ? "99+" : pending}
          </span>
        )}
        <span className="flex-1" />
        <NotificationsBell />
        <button
          type="button"
          onClick={toggle}
          aria-label={theme === "dark" ? "Usar o tema claro" : "Usar o tema escuro"}
          className="flex h-9 w-9 items-center justify-center rounded-control text-fg-3 transition-colors hover:bg-raised hover:text-fg"
        >
          {theme === "dark" ? <Sun size={16} aria-hidden="true" /> : <Moon size={16} aria-hidden="true" />}
        </button>
        <Link
          to="/account"
          aria-label="Sua conta"
          className="flex h-9 w-9 items-center justify-center rounded-full bg-sunken text-xs font-semibold text-fg-2"
        >
          {user?.username?.[0]?.toUpperCase()}
        </Link>
      </header>

      {reachable === false && (
        <p className="flex items-center gap-2 border-b border-hairline bg-warn/10 px-4 py-1.5 text-xs text-warn lg:hidden">
          <StatusDot tone="warn" />
          Servidor fora de contato
        </p>
      )}

      {/* Lateral: navegação em telas lg+. */}
      <aside
        className="fixed inset-y-0 left-0 z-20 hidden w-[232px] flex-col gap-1 border-r border-hairline bg-surface p-3 lg:flex"
        aria-label="Navegação"
      >
        <div className="flex items-center gap-2.5 px-2 pb-5 pt-1">
          <SignalMark />
          <span className="font-display text-[17px] font-bold tracking-tight text-fg">AnomalyDetect</span>
        </div>

        <nav aria-label="Seções" className="flex flex-1 flex-col gap-0.5">
          {NAV.map(({ to, label, icon: Icon }) => {
            const active = isActive(to);
            const badge = to === "/anomalies" && pending > 0 ? pending : null;
            return (
              <Link
                key={to}
                to={to}
                aria-current={active ? "page" : undefined}
                className={clsx(
                  "flex items-center gap-3 rounded-control px-2.5 py-2 text-sm font-medium transition-colors duration-150",
                  active ? "bg-accent/[.14] text-fg" : "text-fg-2 hover:bg-raised hover:text-fg"
                )}
              >
                <Icon size={19} className={active ? "text-accent" : "text-fg-3"} aria-hidden="true" />
                <span className="flex-1">{label}</span>
                {badge !== null && (
                  <span className="tnum font-mono text-micro font-medium text-warn" aria-label={`${badge} em aberto`}>
                    {badge > 99 ? "99+" : badge}
                  </span>
                )}
              </Link>
            );
          })}
        </nav>

        <div className="flex-shrink-0 border-t border-hairline pt-2">
          {reachable === false && (
            <p className="mb-1 flex items-center gap-2 px-2.5 py-1.5 text-xs text-warn">
              <StatusDot tone="warn" />
              Servidor fora de contato
            </p>
          )}
          <Link
            to="/account"
            className={clsx(
              "flex items-center gap-2.5 rounded-control px-2.5 py-2 transition-colors hover:bg-raised",
              location.pathname === "/account" && "bg-raised"
            )}
          >
            <span className="flex h-[30px] w-[30px] flex-shrink-0 items-center justify-center rounded-full bg-sunken font-display text-[13px] font-semibold text-fg-2">
              {user?.username?.[0]?.toUpperCase()}
            </span>
            <span className="min-w-0 flex-1">
              <span className="block truncate text-xs font-medium text-fg">{user?.username}</span>
              <span className="block truncate text-micro text-fg-3">{user?.email}</span>
            </span>
          </Link>
          <div className="mt-1 flex items-center gap-1 px-0.5">
            <NotificationsBell />
            <button
              type="button"
              onClick={toggle}
              aria-label={theme === "dark" ? "Usar o tema claro" : "Usar o tema escuro"}
              className="flex h-8 w-8 items-center justify-center rounded-control border border-edge text-fg-2 transition-colors hover:bg-raised hover:text-fg"
            >
              {theme === "dark" ? <Sun size={14} aria-hidden="true" /> : <Moon size={14} aria-hidden="true" />}
            </button>
            <button
              type="button"
              onClick={handleLogout}
              className="flex-1 rounded-control px-2 py-1.5 text-left text-xs text-fg-3 transition-colors hover:bg-raised hover:text-fg"
            >
              Sair da conta
            </button>
          </div>
        </div>
      </aside>

      <main id="conteudo" className="pb-20 lg:pb-0 lg:pl-[232px]">
        <div className="mx-auto w-full px-4 py-7 sm:px-8 min-[1500px]:px-10 min-[1500px]:py-8">{children}</div>
      </main>

      {/* Barra inferior: navegação abaixo de lg. */}
      <nav
        aria-label="Seções"
        className="fixed inset-x-0 bottom-0 z-30 flex items-stretch justify-around border-t border-hairline bg-surface pb-[env(safe-area-inset-bottom)] lg:hidden"
      >
        {NAV.map(({ to, label, icon: Icon }) => {
          const active = isActive(to);
          const badge = to === "/anomalies" && pending > 0 ? pending : null;
          return (
            <Link
              key={to}
              to={to}
              aria-current={active ? "page" : undefined}
              className={clsx(
                "relative flex min-h-[52px] flex-1 flex-col items-center justify-center gap-0.5 px-1 py-1.5 text-[11px] font-medium",
                active ? "text-accent" : "text-fg-3"
              )}
            >
              <Icon size={19} aria-hidden="true" />
              <span className="truncate">{label}</span>
              {badge !== null && (
                <span
                  className="tnum absolute right-2 top-1 rounded-full bg-warn/15 px-1 font-mono text-[10px] font-medium text-warn"
                  aria-label={`${badge} em aberto`}
                >
                  {badge > 99 ? "99+" : badge}
                </span>
              )}
            </Link>
          );
        })}
      </nav>
    </div>
  );
}
