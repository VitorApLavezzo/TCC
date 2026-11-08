import { useStatus } from "../context/StatusContext";
import { timeAgo } from "../lib/format";
import { Explain } from "./ui/Explain";
import { StatusDot } from "./ui/Layout";
import { LiveDot } from "./ui/SignalTrace";
import { WSStatus } from "../hooks/useWebSocket";

/** Tempo sem leitura que já conta como "o agente parou". */
const STALE_AFTER_MS = 150000;

/** De quando é a leitura na tela e se ela ainda está chegando (agente desligado não aparece "ao vivo"). */
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

  // Horário exato no title: "há 2 min" é o que se lê, a hora cheia é o que se anota.
  const exactTime = lastMetricAt ? new Date(lastMetricAt).toLocaleString("pt-BR") : undefined;

  if (age < STALE_AFTER_MS) {
    return (
      <Tag tone="ok" breathing={wsStatus === "open"} title={exactTime}>
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
    <Tag tone="warn" title={exactTime}>
      Sem leitura {timeAgo(lastMetricAt, now)}
      <Explain text="Este computador parou de enviar dados. Pode estar desligado, sem internet, ou o agente foi encerrado." />
    </Tag>
  );
}

/** `breathing` só no estado "ao vivo": única animação contínua do produto; em outro estado distrairia. */
function Tag({
  children,
  tone,
  breathing,
  title,
}: {
  children: React.ReactNode;
  tone: "ok" | "warn" | "idle";
  breathing?: boolean;
  title?: string;
}) {
  return (
    <span title={title} className="inline-flex items-center gap-1.5 text-xs text-fg-2">
      {breathing ? <LiveDot tone="ok" breathing /> : <StatusDot tone={tone} />}
      {children}
    </span>
  );
}
