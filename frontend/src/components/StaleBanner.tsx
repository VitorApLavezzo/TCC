import { useStatus } from "../context/StatusContext";
import { timeAgo } from "../lib/format";
import { Button } from "./ui/Button";
import { StatusDot } from "./ui/Layout";

/**
 * Aviso de que o que está na tela pode não ser o atual.
 *
 * Aparece só quando há razão para duvidar dos dados, e diz três coisas: o que
 * aconteceu, de quando são os números, e o que fazer. Sem esse aviso, o
 * backend cair deixava o painel exibindo leituras velhas como se fossem atuais.
 */
export function StaleBanner({ onRetry }: { onRetry?: () => void }) {
  const { reachable, online, lastSuccessAt, consecutiveFailures, now } = useStatus();

  if (reachable !== false) return null;

  const since = timeAgo(lastSuccessAt ? new Date(lastSuccessAt) : null, now);
  const offline = !online;

  return (
    <div role="status" className="flex flex-wrap items-center gap-x-4 gap-y-2 rounded-panel border border-warn/30 bg-warn/8 px-4 py-3">
      <StatusDot tone="warn" className="mt-1.5 self-start" />
      <div className="min-w-0 flex-1">
        <p className="text-sm font-medium text-warn">
          {offline ? "Seu dispositivo está sem internet" : "Sem resposta do servidor"}
        </p>
        <p className="mt-0.5 text-xs leading-relaxed text-fg-2">
          {since
            ? `Os dados abaixo são de ${since} e não estão sendo atualizados.`
            : "Ainda não conseguimos carregar nenhum dado."}
          {!offline && consecutiveFailures > 3 && " Verifique se o servidor do AnomalyDetect está ligado."}
        </p>
      </div>
      {onRetry && (
        <Button size="sm" variant="secondary" onClick={onRetry}>
          Tentar de novo
        </Button>
      )}
    </div>
  );
}
