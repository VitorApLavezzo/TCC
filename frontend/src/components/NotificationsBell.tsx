import { useCallback, useEffect, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import { accountApi } from "../services/api";
import { Notification } from "../types";
import { usePolling } from "../hooks/usePolling";
import { Bell } from "lucide-react";
import { StatusDot } from "./ui/Layout";
import { severityTone } from "./ui/Badge";
import { formatDistanceToNow } from "date-fns";
import { ptBR } from "date-fns/locale";

/**
 * O canal "painel" das notificações.
 *
 * O painel recebe TODAS as notificações, inclusive as que a política de
 * excesso não mandou por Telegram ou e-mail — e diz por que cada uma não saiu
 * ("abaixo da severidade mínima", "passou sozinho", "horário silencioso").
 * Sem isso, a pessoa não teria como saber que existe uma decisão sendo tomada
 * em nome dela.
 */
export function NotificationsBell({ placement = "up" }: { placement?: "up" | "down" }) {
  // "up" é a lateral do desktop, onde o sino fica no rodapé; "down" é o
  // cabeçalho do celular, onde abrir para cima jogava o painel fora da tela.
  const down = placement === "down";
  const navigate = useNavigate();
  const [items, setItems] = useState<Notification[]>([]);
  const [unread, setUnread] = useState(0);
  const [open, setOpen] = useState(false);
  const wrapRef = useRef<HTMLDivElement>(null);

  const fetchItems = useCallback(async () => {
    const res = await accountApi.notifications();
    setItems(res.data.notifications);
    setUnread(res.data.unread);
  }, []);
  usePolling(fetchItems, 45000);

  useEffect(() => {
    if (!open) return;
    const onDown = (e: MouseEvent) => {
      if (!wrapRef.current?.contains(e.target as Node)) setOpen(false);
    };
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && setOpen(false);
    document.addEventListener("mousedown", onDown);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("mousedown", onDown);
      document.removeEventListener("keydown", onKey);
    };
  }, [open]);

  const openPanel = async () => {
    const next = !open;
    setOpen(next);
    if (next && unread > 0) {
      try {
        await accountApi.markRead();
        setUnread(0);
      } catch {
        /* a leitura é secundária */
      }
    }
  };

  const go = (n: Notification) => {
    setOpen(false);
    if (n.link) navigate(n.link);
  };

  return (
    <div ref={wrapRef} className="relative">
      <button
        type="button"
        onClick={openPanel}
        aria-label={unread > 0 ? `${unread} notificações não lidas` : "Notificações"}
        aria-expanded={open}
        className={`relative flex items-center justify-center rounded-control text-fg-3 transition-colors hover:bg-raised hover:text-fg ${
          down ? "h-9 w-9" : "h-7 w-7"
        }`}
      >
        <Bell size={down ? 16 : 14} aria-hidden="true" />
        {unread > 0 && <span className="absolute right-1 top-1 h-1.5 w-1.5 rounded-full bg-accent" />}
      </button>

      {open && (
        <div
          className={`z-40 overflow-hidden rounded-panel border border-edge bg-surface shadow-float ${
            down ? "fixed inset-x-3 top-[3.75rem]" : "absolute bottom-full left-0 mb-2 w-80 max-w-[90vw]"
          }`}
        >
          <p className="border-b border-hairline px-3.5 py-2.5 text-xs font-medium text-fg">Notificações</p>
          <div className="max-h-96 overflow-y-auto">
            {items.length === 0 ? (
              <p className="px-3.5 py-4 text-xs text-fg-3">Nada por aqui ainda.</p>
            ) : (
              items.slice(0, 25).map((n) => (
                <button
                  key={n.id}
                  type="button"
                  onClick={() => go(n)}
                  className="block w-full border-b border-hairline px-3.5 py-2.5 text-left transition-colors last:border-0 hover:bg-raised"
                >
                  <span className="flex items-start gap-2">
                    <StatusDot tone={severityTone(n.severity)} className="mt-1.5" />
                    <span className="min-w-0 flex-1">
                      <span className="block text-xs font-medium text-fg">{n.title}</span>
                      {n.body && <span className="clamp-2 mt-0.5 block text-micro leading-relaxed text-fg-2">{n.body}</span>}
                      <span className="mt-1 flex flex-wrap items-center gap-x-2 text-micro text-fg-3">
                        <span>
                          {formatDistanceToNow(new Date(n.created_at), { addSuffix: true, locale: ptBR })}
                        </span>
                        {n.status !== "sent" && n.status_reason && <span>· {n.status_reason}</span>}
                        {n.channels && Object.keys(n.channels).length > 1 && <span>· enviado</span>}
                      </span>
                    </span>
                  </span>
                </button>
              ))
            )}
          </div>
        </div>
      )}
    </div>
  );
}
