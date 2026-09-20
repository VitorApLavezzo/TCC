import { useStatus } from "../context/StatusContext";
import { timeAgo } from "../lib/format";
import { Explain } from "./ui/Explain";
import { StatusDot } from "./ui/Layout";
import { LiveDot } from "./ui/SignalTrace";
import { WSStatus } from "../hooks/useWebSocket";

/** Quantos segundos sem leitura já contam como "o agente parou". */
const STALE_AFTER_MS = 150000;

/**
 * De quando é a leitura na tela e se ela ainda está chegando.
 *
 * Substitui o selo "AO VIVO", que acendia na primeira mensagem do WebSocket e
 * nunca apagava — um agente desligado seguia aparecendo como ao vivo. É texto
 * com um ponto, não uma pílula: é metadado, não destaque.
 */
export function FreshnessTag({
  lastMetricAt,
  wsStatus,
  paused,
}: {
  lastMetricAt?: string | null;
  wsStatus: WSStatus;
  /** Coleta pausada pelo usuário — não é falha. */
  paused?: boolean;
}) {
  const { now } = useStatus();

  if (paused) {
    return <Tag tone="idle">Coleta pausada</Tag>;
  }

  const at = lastMetricAt ? new Date(lastMetricAt).getTime() : null;
  const age = at ? now - at : null;

  if (age === null) {
    return <Tag tone="idle">Aguardando a primeira leitura</Tag>;
  }

  // Horário exato no title: "há 2 min" é o que se lê, mas a hora cheia é o
  // que se anota.
  const exato = lastMetricAt ? new Date(lastMetricAt).toLocaleString("pt-BR") : undefined;

  if (age < STALE_AFTER_MS) {
    return (
      <Tag tone="ok" breathing={wsStatus === "open"} title={exato}>
        {wsStatus === "open" ? (
          <>
            Ao vivo
            <Explain term="ao_vivo" />
          </>
        ) : (
          `Atualizado ${timeAgo(lastMetricAt, now)}`
        )}
      </Tag>
    );
  }

  return (
    <Tag tone="warn" title={exato}>
      Sem leitura {timeAgo(lastMetricAt, now)}
      <Explain text="Este computador parou de enviar dados. Pode estar desligado, sem internet, ou o agente foi encerrado." />
    </Tag>
  );
}

/**
 * `breathing` só é usado no estado "ao vivo": é a única animação contínua do
 * produto, de baixa amplitude e ciclo longo. Serve para dizer que o sistema
 * está observando agora — em qualquer outro estado ela seria só distração.
 */
function Tag({
  children,
  tone,
  breathing,
  title,
}: {
  children: React.ReactNode;
  tone: "ok" | "warn" | "idle";
  breathing?: boolean;
  /** Horário exato da leitura, para quem precisa anotar. */
  title?: string;
}) {
  return (
    <span title={title} className="inline-flex items-center gap-1.5 text-xs text-fg-2">
      {breathing ? <LiveDot tone="ok" breathing /> : <StatusDot tone={tone} />}
      {children}
    </span>
  );
}
