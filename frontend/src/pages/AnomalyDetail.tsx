import { useState, useEffect, useRef, useCallback } from "react";
import { useParams, useNavigate } from "react-router-dom";
import { anomaliesApi, explanationsApi, machinesApi, metricsApi, errorMessage } from "../services/api";
import { Anomaly, Metric, ANOMALY_TYPE_LABELS } from "../types";
import { Severity } from "../components/ui/Badge";
import { Section, Panel, DataList, DataRow, StatusDot } from "../components/ui/Layout";
import { Button, TextButton } from "../components/ui/Button";
import { Explain } from "../components/ui/Explain";
import { Skeleton } from "../components/ui/Skeleton";
import { EmptyState } from "../components/ui/EmptyState";
import { MetricChart } from "../components/charts/MetricChart";
import { useToast } from "../components/ui/Toast";
import { ANOMALY_TYPE_HINTS, SEVERITY_URGENCY } from "../lib/glossary";
import { health, LEVEL_CLASS } from "../lib/health";
import { format } from "date-fns";
import { ptBR } from "date-fns/locale";
import { ArrowLeft } from "lucide-react";

/** Qual métrica ilustra melhor cada tipo de anomalia. */
const CHART_FOR: Record<string, { key: keyof Metric; label: string; term: string; threshold?: number }> = {
  high_cpu: { key: "cpu_percent", label: "Processador (%)", term: "cpu", threshold: 80 },
  cpu_loop: { key: "cpu_percent", label: "Processador (%)", term: "cpu", threshold: 80 },
  high_memory: { key: "mem_percent", label: "Memória (%)", term: "memoria", threshold: 85 },
  memory_leak: { key: "mem_percent", label: "Memória (%)", term: "memoria", threshold: 85 },
  disk_full: { key: "disk_percent", label: "Disco (%)", term: "disco", threshold: 85 },
  network_spike: { key: "net_connections", label: "Conexões de rede", term: "conexoes" },
  ddos_indicator: { key: "net_connections", label: "Conexões de rede", term: "conexoes" },
  resource_exhaustion: { key: "cpu_percent", label: "Processador (%)", term: "cpu", threshold: 80 },
};

export function AnomalyDetail() {
  const { id } = useParams<{ id: string }>();
  const navigate = useNavigate();
  const toast = useToast();
  const [anomaly, setAnomaly] = useState<Anomaly | null>(null);
  const [machineName, setMachineName] = useState("");
  const [context, setContext] = useState<Metric[]>([]);
  const [loading, setLoading] = useState(true);
  const [regenerating, setRegenerating] = useState(false);
  const [notFound, setNotFound] = useState(false);
  const pollingRef = useRef<ReturnType<typeof setInterval> | null>(null);

  const stopPolling = () => {
    if (pollingRef.current) clearInterval(pollingRef.current);
    pollingRef.current = null;
  };

  useEffect(() => {
    if (!id) return;
    let cancelled = false;

    anomaliesApi
      .get(Number(id))
      .then((res) => {
        if (cancelled) return;
        const a: Anomaly = res.data;
        setAnomaly(a);

        machinesApi
          .get(a.machine_id)
          .then((mr) => !cancelled && setMachineName(mr.data.name))
          .catch(() => {});

        // Janela em volta da detecção, para o gráfico mostrar o pico.
        const hoursAgo = Math.ceil((Date.now() - new Date(a.detected_at).getTime()) / 3600000) + 2;
        metricsApi
          .list(a.machine_id, Math.min(Math.max(hoursAgo, 3), 168))
          .then((mr) => !cancelled && setContext(mr.data))
          .catch(() => {});
      })
      .catch(() => !cancelled && setNotFound(true))
      .finally(() => !cancelled && setLoading(false));

    return () => {
      cancelled = true;
      stopPolling();
    };
  }, [id]);

  // Enquanto a IA não devolve as causas, recarrega sozinho.
  useEffect(() => {
    if (!anomaly) return;
    if ((anomaly.explanation?.possible_causes?.length ?? 0) > 0) {
      stopPolling();
      return;
    }
    stopPolling();
    pollingRef.current = setInterval(async () => {
      try {
        const res = await anomaliesApi.get(anomaly.id);
        if ((res.data.explanation?.possible_causes?.length ?? 0) > 0) {
          setAnomaly(res.data);
          stopPolling();
        }
      } catch {
        // Falha momentânea: a próxima tentativa continua daqui.
      }
    }, 4000);
    return () => stopPolling();
  }, [anomaly?.id, anomaly?.explanation?.possible_causes?.length]);

  const handleRegenerate = useCallback(async () => {
    if (!anomaly) return;
    setRegenerating(true);
    try {
      const res = await explanationsApi.regenerate(anomaly.id);
      setAnomaly((prev) => (prev ? { ...prev, explanation: res.data } : prev));
      toast.success("Explicação gerada.");
    } catch (err) {
      toast.error(
        errorMessage(err, "Não foi possível gerar a explicação."),
        "O serviço de IA pode estar indisponível. As causas aparecem assim que ele responder."
      );
    } finally {
      setRegenerating(false);
    }
  }, [anomaly, toast]);

  const handleResolve = async () => {
    if (!anomaly) return;
    try {
      const res = await anomaliesApi.resolve(anomaly.id, !anomaly.is_resolved);
      setAnomaly(res.data);
      toast.success(anomaly.is_resolved ? "Aviso reaberto." : "Aviso resolvido.");
    } catch (err) {
      toast.error(errorMessage(err, "Não foi possível mudar o estado deste aviso."));
    }
  };

  if (loading) {
    return (
      <div className="max-w-3xl space-y-6">
        <Skeleton className="h-4 w-32" />
        <Skeleton className="h-7 w-72" />
        <Skeleton className="h-12 w-full" />
        <Skeleton className="h-32 w-full rounded-panel" />
      </div>
    );
  }

  if (notFound || !anomaly) {
    return (
      <div className="max-w-3xl">
        <EmptyState
          title="Este aviso não existe mais"
          body="Ele pode ter sido removido junto com o computador a que pertencia."
          action={
            <Button variant="primary" onClick={() => navigate("/anomalies")}>
              Voltar para os avisos
            </Button>
          }
        />
      </div>
    );
  }

  const exp = anomaly.explanation;
  const typeLabel = ANOMALY_TYPE_LABELS[anomaly.anomaly_type] || anomaly.anomaly_type;
  const hint = ANOMALY_TYPE_HINTS[anomaly.anomaly_type];
  const chart = CHART_FOR[anomaly.anomaly_type];
  const urgency =
    anomaly.severity === "critical"
      ? LEVEL_CLASS.crit
      : anomaly.severity === "low"
        ? LEVEL_CLASS.unknown
        : LEVEL_CLASS.warn;

  return (
    <div className="max-w-3xl space-y-8">
      <TextButton onClick={() => navigate("/anomalies")} className="inline-flex items-center gap-1.5 text-fg-2">
        <ArrowLeft size={12} aria-hidden="true" />
        Todos os avisos
      </TextButton>

      <header className="border-b border-hairline pb-4">
        <div className="flex flex-wrap items-baseline gap-x-4 gap-y-1">
          <h1 className="text-lg font-semibold tracking-tight text-fg">{typeLabel}</h1>
          {anomaly.is_resolved ? (
            <span className="flex items-center gap-1.5 text-xs text-fg-3">
              <StatusDot tone="idle" />
              Resolvida
            </span>
          ) : (
            <Severity severity={anomaly.severity} />
          )}
        </div>
        {hint && <p className="mt-2 max-w-prose text-sm leading-relaxed text-fg-2">{hint}</p>}
        <p className="tnum mt-2.5 flex flex-wrap items-center gap-x-4 gap-y-1 text-xs text-fg-3">
          {machineName && <span>{machineName}</span>}
          <span>{format(new Date(anomaly.detected_at), "dd/MM/yyyy 'às' HH:mm:ss", { locale: ptBR })}</span>
        </p>

        <div className="mt-4 flex flex-wrap items-center gap-2">
          <Button variant={anomaly.is_resolved ? "secondary" : "primary"} onClick={handleResolve}>
            {anomaly.is_resolved ? "Reabrir aviso" : "Marcar como resolvido"}
          </Button>
          {exp && (
            <Button variant="quiet" loading={regenerating} loadingLabel="Gerando..." onClick={handleRegenerate}>
              Gerar nova explicação
            </Button>
          )}
        </div>
      </header>

      {/* Único bloco com fundo tingido da aplicação — reservado à urgência. */}
      <p className={`rounded-panel border px-4 py-2.5 text-sm ${urgency.border} ${urgency.bg} ${urgency.text}`}>
        {SEVERITY_URGENCY[anomaly.severity]}
      </p>

      <Section title="O que aconteceu" actions={exp?.model_used ? <span className="text-micro text-fg-3">{exp.model_used}</span> : undefined}>
        {exp ? (
          <div className="space-y-3">
            <p className="max-w-prose text-base leading-relaxed text-fg">{exp.summary}</p>
            {exp.detailed_explanation && (
              <p className="max-w-prose whitespace-pre-line text-sm leading-relaxed text-fg-2">
                {exp.detailed_explanation}
              </p>
            )}
            {exp.severity_justification && (
              <p className="max-w-prose text-xs leading-relaxed text-fg-3">{exp.severity_justification}</p>
            )}
          </div>
        ) : (
          <EmptyState
            title="A explicação em linguagem simples ainda não chegou"
            body="Os dados técnicos abaixo já estão completos. A análise escrita depende do serviço de IA, que pode estar ocupado ou desligado."
            action={
              <Button variant="primary" loading={regenerating} loadingLabel="Gerando..." onClick={handleRegenerate}>
                Gerar a explicação agora
              </Button>
            }
          />
        )}
      </Section>

      {chart && context.length > 1 && (
        <Section title="O momento em que aconteceu" description="A linha vertical marca o instante da detecção">
          <MetricChart
            metrics={context}
            dataKey={chart.key}
            label={chart.label}
            term={chart.term}
            threshold={chart.threshold}
            markAt={anomaly.detected_at}
            unit={chart.key === "net_connections" ? "" : "%"}
            domain={
              chart.key === "net_connections"
                ? [0, Math.max(...context.map((m) => m.net_connections ?? 0)) + 10]
                : undefined
            }
          />
        </Section>
      )}

      {exp?.recommendations && exp.recommendations.length > 0 && (
        <Section title="O que fazer agora" description="Na ordem, do mais simples para o mais avançado">
          <ol className="divide-y divide-hairline border-y border-hairline">
            {exp.recommendations.map((rec, i) => (
              <li key={i} className="flex gap-3 py-3">
                <span className="tnum w-4 flex-shrink-0 text-sm text-fg-3">{i + 1}</span>
                <span className="max-w-prose text-sm leading-relaxed text-fg-2">{rec}</span>
              </li>
            ))}
          </ol>
        </Section>
      )}

      <div className="grid grid-cols-1 gap-6 md:grid-cols-2">
        <Section title="Por que isso pode ter acontecido" flush>
          {exp?.possible_causes && exp.possible_causes.length > 0 ? (
            <ol className="divide-y divide-hairline border-t border-hairline">
              {exp.possible_causes.map((cause, i) => (
                <li key={i} className="flex gap-3 py-2.5">
                  <span className="tnum w-4 flex-shrink-0 text-sm text-fg-3">{i + 1}</span>
                  <span className="text-sm leading-relaxed text-fg-2">{cause}</span>
                </li>
              ))}
            </ol>
          ) : exp ? (
            <p className="border-t border-hairline pt-3 text-sm text-fg-3">
              Analisando as causas. Esta parte atualiza sozinha quando a IA terminar.
            </p>
          ) : (
            <p className="border-t border-hairline pt-3 text-sm text-fg-3">
              As causas prováveis vêm junto com a explicação da IA.
            </p>
          )}
        </Section>

        <Section title="Dados da leitura" flush>
          <Panel className="mt-3 px-4 py-2">
            <DataList>
              {anomaly.affected_metrics && Object.keys(anomaly.affected_metrics).length > 0 ? (
                Object.entries(anomaly.affected_metrics)
                  .filter(([key, val]) => key !== "_behavior" && typeof val !== "object")
                  .map(([key, val]) => {
                    const reading =
                      typeof val !== "number"
                        ? null
                        : key.includes("cpu")
                          ? health.cpu(val)
                          : key.includes("mem")
                            ? health.memory(val)
                            : key.includes("disk")
                              ? health.disk(val)
                              : null;
                    return (
                      <DataRow
                        key={key}
                        label={key.replace(/_/g, " ").replace(/^./, (c) => c.toUpperCase())}
                        value={typeof val === "number" ? `${val.toFixed(1)}%` : String(val)}
                        note={reading?.label}
                        tone={reading && reading.level !== "unknown" ? reading.level : undefined}
                      />
                    );
                  })
              ) : (
                <DataRow label="Métricas" value="nenhuma registrada" />
              )}

              {anomaly.responsible_process && (
                <DataRow label="Programa responsável" value={anomaly.responsible_process} mono />
              )}

              {anomaly.anomaly_score !== null && anomaly.anomaly_score !== undefined && (
                <DataRow
                  label="Desvio do padrão"
                  value={anomaly.anomaly_score.toFixed(4)}
                  hint={<Explain term="score" />}
                />
              )}
            </DataList>
          </Panel>
        </Section>
      </div>
    </div>
  );
}
