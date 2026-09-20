import { ReactNode, useCallback, useEffect, useRef, useState } from "react";
import { Link, useLocation, useNavigate, useSearchParams } from "react-router-dom";
import { clsx } from "clsx";
import { Sun, Moon, LayoutGrid, Monitor, Bell, MessageSquare, Search } from "lucide-react";
import { useAuth } from "../context/AuthContext";
import { useStatus } from "../context/StatusContext";
import { useTheme } from "../context/ThemeContext";
import { anomaliesApi } from "../services/api";
import { usePolling } from "../hooks/usePolling";
import { StatusDot } from "./ui/Layout";
import { SignalMark } from "./ui/SignalMark";
import { NotificationsBell } from "./NotificationsBell";
import { CommandPalette } from "./ui/CommandPalette";
import { ShortcutsSheet } from "./ui/ShortcutsSheet";
import { useT } from "../lib/i18n";

/**
 * Navegação principal: quatro destinos, os que se usa todo dia.
 *
 * "Pesquisa" ocupava o quinto lugar — e ela é ferramenta de quem escreve o
 * trabalho, não de quem monitora um computador. No celular, cinco rótulos
 * espremiam a barra inferior a ponto de truncar. As telas de pesquisa
 * continuam a um clique, agrupadas em "Avançado" e na busca do Ctrl+K.
 */
const NAV = [
  { to: "/", key: "nav.dashboard", label: "Painel", icon: LayoutGrid },
  { to: "/machines", key: "nav.machines", label: "Computadores", icon: Monitor },
  { to: "/anomalies", key: "nav.anomalies", label: "Avisos", icon: Bell },
  { to: "/pergunte", key: "nav.ask", label: "Pergunte", icon: MessageSquare },
];

const AVANCADO = [
  { to: "/pesquisa", key: "nav.research", label: "Pesquisa" },
  { to: "/demonstracao", key: "nav.demo", label: "Demonstração" },
  { to: "/estudo", key: "nav.study", label: "Estudo" },
];

export function AppShell({ children }: { children: ReactNode }) {
  const { user, logout } = useAuth();
  const { reachable } = useStatus();
  const { theme, toggle } = useTheme();
  const location = useLocation();
  const navigate = useNavigate();
  const [params] = useSearchParams();
  const t = useT();
  const [pending, setPending] = useState(0);
  const [palette, setPalette] = useState(false);
  const [shortcuts, setShortcuts] = useState(false);
  const mainRef = useRef<HTMLElement>(null);
  const anterior = useRef(0);
  const [anuncio, setAnuncio] = useState("");

  // Modo apresentação: sem menu, sem e-mail na tela, tipografia maior. Para
  // projetar na banca sem mostrar a moldura do produto.
  const apresentacao = params.get("apresentacao") === "1";

  const fetchPending = useCallback(async () => {
    const res = await anomaliesApi.list({ hours: 168, unresolved_only: true });
    setPending(res.data.length);
  }, []);
  usePolling(fetchPending, 45000);

  // Aviso novo chegando enquanto a pessoa olha outra tela não deixava rastro
  // para quem usa leitor de tela. A região viva anuncia a mudança, e só ela.
  useEffect(() => {
    if (pending > anterior.current && anterior.current !== 0) {
      setAnuncio(`${pending} ${pending === 1 ? "aviso em aberto" : "avisos em aberto"}`);
    }
    anterior.current = pending;
  }, [pending]);

  // Numa aplicação de página única, trocar de rota não move o foco: quem
  // navega por teclado continua no menu e o leitor de tela não anuncia nada.
  useEffect(() => {
    mainRef.current?.focus();
  }, [location.pathname]);

  useEffect(() => {
    let ultimaTecla = "";
    const onKey = (e: KeyboardEvent) => {
      const alvo = e.target as HTMLElement;
      const digitando = /^(INPUT|TEXTAREA|SELECT)$/.test(alvo?.tagName || "") || alvo?.isContentEditable;
      if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "k") {
        e.preventDefault();
        setPalette(true);
        return;
      }
      if (digitando) return;
      if (e.key === "/") {
        e.preventDefault();
        setPalette(true);
      } else if (e.key === "?") {
        setShortcuts(true);
      } else if (ultimaTecla === "g") {
        const destino = { p: "/", c: "/machines", a: "/anomalies", q: "/pergunte" }[e.key];
        if (destino) navigate(destino);
      }
      ultimaTecla = e.key;
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [navigate]);

  const handleLogout = () => {
    logout();
    navigate("/login");
  };

  const isActive = (to: string) => (to === "/" ? location.pathname === "/" : location.pathname.startsWith(to));

  if (apresentacao) {
    return (
      <div className="min-h-screen bg-canvas" data-present="1">
        <main id="conteudo" className="mx-auto w-full max-w-5xl px-6 py-10 text-[1.08rem]">
          {children}
        </main>
      </div>
    );
  }

  return (
    <div className="min-h-screen bg-canvas">
      <a
        href="#conteudo"
        className="sr-only focus:not-sr-only focus:absolute focus:left-4 focus:top-4 focus:z-50 focus:rounded-control focus:bg-accent focus:px-3 focus:py-2 focus:text-sm focus:font-medium focus:text-canvas"
      >
        {t("nav.skip", "Ir para o conteúdo")}
      </a>
      <p aria-live="polite" className="sr-only">{anuncio}</p>

      <header className="sticky top-0 z-30 flex h-14 items-center gap-3 border-b border-hairline bg-surface px-4 lg:hidden">
        <SignalMark />
        <span className="font-display text-sm font-semibold tracking-tight text-fg">AnomalyDetect</span>
        {pending > 0 && (
          <span className="tnum ml-1 rounded-full bg-warn/15 px-2 py-0.5 font-mono text-micro font-medium text-warn">
            {pending > 99 ? "99+" : pending}
          </span>
        )}
        <span className="flex-1" />
        <button
          type="button"
          onClick={() => setPalette(true)}
          aria-label={t("action.search", "Buscar")}
          className="flex h-9 w-9 items-center justify-center rounded-control text-fg-3 transition-colors hover:bg-raised hover:text-fg"
        >
          <Search size={16} aria-hidden="true" />
        </button>
        <NotificationsBell />
        <button
          type="button"
          onClick={toggle}
          aria-label={theme === "dark" ? t("shell.theme.toLight", "Usar o tema claro") : t("shell.theme.toDark", "Usar o tema escuro")}
          className="flex h-9 w-9 items-center justify-center rounded-control text-fg-3 transition-colors hover:bg-raised hover:text-fg"
        >
          {theme === "dark" ? <Sun size={16} aria-hidden="true" /> : <Moon size={16} aria-hidden="true" />}
        </button>
        <Link
          to="/account"
          aria-label={t("nav.account", "Sua conta")}
          className="flex h-9 w-9 items-center justify-center rounded-full bg-sunken text-xs font-semibold text-fg-2"
        >
          {user?.username?.[0]?.toUpperCase()}
        </Link>
      </header>

      {reachable === false && (
        <p className="flex items-center gap-2 border-b border-hairline bg-warn/10 px-4 py-1.5 text-xs text-warn lg:hidden">
          <StatusDot tone="warn" />
          {t("shell.offline", "Servidor fora de contato")}
        </p>
      )}

      <aside
        className="fixed inset-y-0 left-0 z-20 hidden w-[232px] flex-col gap-1 border-r border-hairline bg-surface p-3 lg:flex"
        aria-label="Navegação"
      >
        <div className="flex items-center gap-2.5 px-2 pb-4 pt-1">
          <SignalMark />
          <span className="font-display text-[17px] font-bold tracking-tight text-fg">AnomalyDetect</span>
        </div>

        <button
          type="button"
          onClick={() => setPalette(true)}
          className="mb-2 flex items-center gap-2 rounded-control border border-edge px-2.5 py-1.5 text-xs text-fg-3 transition-colors hover:border-fg-3 hover:text-fg-2"
        >
          <Search size={13} aria-hidden="true" />
          <span className="flex-1 text-left">{t("action.search", "Buscar")}</span>
          <kbd className="rounded border border-edge px-1 font-mono text-[10px]">Ctrl K</kbd>
        </button>

        <nav aria-label={t("nav.sections", "Seções")} className="flex flex-1 flex-col gap-0.5">
          {NAV.map(({ to, key, label, icon: Icon }) => {
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
                <span className="flex-1">{t(key, label)}</span>
                {badge !== null && (
                  <span className="tnum font-mono text-micro font-medium text-warn" aria-label={`${badge} ${t("shell.open", "em aberto")}`}>
                    {badge > 99 ? "99+" : badge}
                  </span>
                )}
              </Link>
            );
          })}

          <p className="channel-label mt-5 px-2.5">{t("nav.advanced", "Avançado")}</p>
          {AVANCADO.map(({ to, key, label }) => (
            <Link
              key={to}
              to={to}
              aria-current={isActive(to) ? "page" : undefined}
              className={clsx(
                "rounded-control px-2.5 py-1.5 text-xs transition-colors",
                isActive(to) ? "bg-raised text-fg" : "text-fg-3 hover:bg-raised hover:text-fg-2"
              )}
            >
              {t(key, label)}
            </Link>
          ))}
        </nav>

        <div className="flex-shrink-0 border-t border-hairline pt-2">
          {reachable === false && (
            <p className="mb-1 flex items-center gap-2 px-2.5 py-1.5 text-xs text-warn">
              <StatusDot tone="warn" />
              {t("shell.offline", "Servidor fora de contato")}
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
              aria-label={theme === "dark" ? t("shell.theme.toLight", "Usar o tema claro") : t("shell.theme.toDark", "Usar o tema escuro")}
              className="flex h-8 w-8 items-center justify-center rounded-control border border-edge text-fg-2 transition-colors hover:bg-raised hover:text-fg"
            >
              {theme === "dark" ? <Sun size={14} aria-hidden="true" /> : <Moon size={14} aria-hidden="true" />}
            </button>
            <button
              type="button"
              onClick={handleLogout}
              className="flex-1 rounded-control px-2 py-1.5 text-left text-xs text-fg-3 transition-colors hover:bg-raised hover:text-fg"
            >
              {t("nav.logout", "Sair da conta")}
            </button>
          </div>
        </div>
      </aside>

      {/* tabIndex -1: alvo do foco a cada troca de rota, sem entrar na ordem do Tab. */}
      <main ref={mainRef} id="conteudo" tabIndex={-1} className="pb-20 outline-none lg:pb-0 lg:pl-[232px]">
        <div className="mx-auto w-full px-4 py-7 sm:px-8 min-[1500px]:px-10 min-[1500px]:py-8">{children}</div>
      </main>

      <nav
        aria-label={t("nav.sections", "Seções")}
        className="fixed inset-x-0 bottom-0 z-30 flex items-stretch justify-around border-t border-hairline bg-surface pb-[env(safe-area-inset-bottom)] lg:hidden"
      >
        {NAV.map(({ to, key, label, icon: Icon }) => {
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
              <span className="truncate">{t(key, label)}</span>
              {badge !== null && (
                <span
                  className="tnum absolute right-2 top-1 rounded-full bg-warn/15 px-1 font-mono text-[10px] font-medium text-warn"
                  aria-label={`${badge} ${t("shell.open", "em aberto")}`}
                >
                  {badge > 99 ? "99+" : badge}
                </span>
              )}
            </Link>
          );
        })}
      </nav>

      <CommandPalette open={palette} onClose={() => setPalette(false)} />
      <ShortcutsSheet open={shortcuts} onClose={() => setShortcuts(false)} />
    </div>
  );
}
