import { useState, useEffect, useRef, useCallback } from "react";
import { useParams, useNavigate } from "react-router-dom";
import { anomaliesApi, explanationsApi, machinesApi, metricsApi, errorMessage } from "../services/api";
import { Anomaly, Machine, Metric, Incident, ANOMALY_TYPE_LABELS, SECURITY_TYPES, LanguageLevel } from "../types";
import { Severity } from "../components/ui/Badge";
import { Section, Panel, DataList, DataRow, StatusDot } from "../components/ui/Layout";
import { Button, TextButton } from "../components/ui/Button";
import { Disclosure } from "../components/ui/Disclosure";
import { RankedCauses } from "../components/AnomalyExplanation";
import { Explain } from "../components/ui/Explain";
import { Skeleton } from "../components/ui/Skeleton";
import { EmptyState } from "../components/ui/EmptyState";
import { MetricChart } from "../components/charts/MetricChart";
import { useToast } from "../components/ui/Toast";
import { ANOMALY_TYPE_HINTS, SEVERITY_URGENCY } from "../lib/glossary";
import { processName } from "../lib/format";
import { health, LEVEL_CLASS, THRESHOLDS } from "../lib/health";
import { Feedback, VerificationTag } from "../components/anomaly/Feedback";
import { AdaptiveSteps } from "../components/anomaly/AdaptiveSteps";
import { AnomalyActions } from "../components/anomaly/Actions";
import { PredictionCheck } from "../components/anomaly/PredictionCheck";
import { IncidentChain } from "../components/anomaly/IncidentChain";
import { ShareButton } from "../components/anomaly/ShareButton";
import { Replay } from "../components/anomaly/Replay";
import {
  CounterfactualCard,
  VerificationBadge,
  DestinationTag,
  LanguageLevelSwitch,
  RatingButtons,
} from "../components/anomaly/ExplanationExtras";
import { format } from "date-fns";
import { ptBR } from "date-fns/locale";
import { ArrowLeft, ShieldAlert } from "lucide-react";

const CPU = { key: "cpu_percent" as keyof Metric, label: "Processador", term: "cpu", threshold: THRESHOLDS.cpu.warn };
const MEM = { key: "mem_percent" as keyof Metric, label: "Memória", term: "memoria", threshold: THRESHOLDS.memory.warn };
const NET = { key: "net_connections" as keyof Metric, label: "Conexões de rede", term: "conexoes" };

const CHART_FOR: Record<string, { key: keyof Metric; label: string; term: string; threshold?: number }> = {
  high_cpu: CPU, cpu_loop: CPU, resource_exhaustion: CPU, thermal_throttling: CPU,
  high_memory: MEM, memory_leak: MEM,
  disk_full: { key: "disk_percent", label: "Disco", term: "disco", threshold: THRESHOLDS.disk.warn },
  disk_forecast: { key: "disk_percent", label: "Disco", term: "disco", threshold: THRESHOLDS.disk.warn },
  network_spike: NET, ddos_indicator: NET,
};

export function AnomalyDetail() {
  const { id } = useParams<{ id: string }>();
  const navigate = useNavigate();
  const toast = useToast();
  const [anomaly, setAnomaly] = useState<Anomaly | null>(null);
  const [machine, setMachine] = useState<Machine | null>(null);
  const [incident, setIncident] = useState<Incident | null>(null);
  const [blackboxId, setBlackboxId] = useState<number | null>(null);
  const [context, setContext] = useState<Metric[]>([]);
  const [loading, setLoading] = useState(true);
  const [regenerating, setRegenerating] = useState(false);
  const [notFound, setNotFound] = useState(false);
  const [level, setLevel] = useState<LanguageLevel>("leigo");
  const [variant, setVariant] = useState<any | null>(null);
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
        setLevel(a.explanation?.language_level ?? "leigo");
        machinesApi.get(a.machine_id).then((mr) => !cancelled && setMachine(mr.data)).catch(() => {});
        anomaliesApi
          .context(a.id)
          .then((cr) => {
            if (cancelled) return;
            setIncident(cr.data.incident);
            setBlackboxId(cr.data.blackbox?.id ?? null);
          })
          .catch(() => {});
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
        /* tenta de novo */
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
      setVariant(null);
      setLevel(res.data.language_level ?? "leigo");
      toast.success("Explicação gerada.");
    } catch (err) {
      toast.error(errorMessage(err, "Não foi possível gerar a explicação."));
    } finally {
      setRegenerating(false);
    }
  }, [anomaly, toast]);

  const handleResolveToggle = async () => {
    if (!anomaly) return;
    try {
      const res = await anomaliesApi.resolve(anomaly.id, !anomaly.is_resolved);
      setAnomaly(res.data);
      toast.success(anomaly.is_resolved ? "Aviso reaberto." : "Aviso resolvido.");
    } catch (err) {
      toast.error(errorMessage(err));
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
          action={<Button variant="primary" onClick={() => navigate("/anomalies")}>Voltar para os avisos</Button>}
        />
      </div>
    );
  }

  const exp = anomaly.explanation;
  const shown = variant ?? exp;
  const typeLabel = ANOMALY_TYPE_LABELS[anomaly.anomaly_type] || anomaly.anomaly_type;
  const chart = CHART_FOR[anomaly.anomaly_type];
  const isSecurity = SECURITY_TYPES.has(anomaly.anomaly_type);
  const verdict = shown?.severity_justification || SEVERITY_URGENCY[anomaly.severity];
  const lead = shown?.summary || ANOMALY_TYPE_HINTS[anomaly.anomaly_type];
  const urgency =
    anomaly.severity === "critical" ? LEVEL_CLASS.crit : anomaly.severity === "low" ? LEVEL_CLASS.unknown : LEVEL_CLASS.warn;

  return (
    <div className="max-w-3xl">
      <TextButton onClick={() => navigate("/anomalies")} className="inline-flex items-center gap-1.5 text-fg-2">
        <ArrowLeft size={12} aria-hidden="true" />
        Todos os avisos
      </TextButton>

      <header className="mt-6">
        <p className="flex items-center gap-2">
          <span className="h-[7px] w-[7px] rotate-45 bg-accent" aria-hidden="true" />
          <span className="channel-label">Detectado</span>
          <span className="tnum font-mono text-micro text-fg-2">
            {format(new Date(anomaly.detected_at), "dd/MM/yyyy 'às' HH:mm:ss", { locale: ptBR })}
          </span>
        </p>
        <div className="mt-2.5 flex flex-wrap items-center gap-x-4 gap-y-1">
          <h1 className="text-lg font-semibold tracking-tight text-fg">{typeLabel}</h1>
          {isSecurity && (
            <span className="inline-flex items-center gap-1 text-xs font-medium text-crit">
              <ShieldAlert size={12} aria-hidden="true" />
              Segurança
            </span>
          )}
          {anomaly.is_resolved ? (
            <span className="flex items-center gap-1.5 text-xs text-fg-3">
              <StatusDot tone="idle" />
              Resolvida
            </span>
          ) : (
            <Severity severity={anomaly.severity} />
          )}
        </div>
        {(machine?.name || processName(anomaly)) && (
          <p className="mt-2 flex flex-wrap items-center gap-x-4 gap-y-1 text-xs text-fg-3">
            {machine?.name && <span>{machine.name}</span>}
            {processName(anomaly) && <span className="font-mono text-fg-2">{processName(anomaly)}</span>}
            {anomaly.source && anomaly.source !== "behavior" && anomaly.source !== "ml" && (
              <span className="text-fg-3">via {anomaly.source === "forecast" ? "previsão" : anomaly.source === "fleet" ? "comparação entre computadores" : anomaly.source === "agent_event" ? "evento do computador" : anomaly.source}</span>
            )}
          </p>
        )}
      </header>

      {/*
        Ressalva, não alerta: explica por que este aviso existe no painel sem
        ter chegado como notificação. Sem cor de estado — a cor é do problema.
      */}
      {anomaly.during_learning && (
        <p className="mt-4 max-w-prose border-l-2 border-edge pl-4 text-xs leading-relaxed text-fg-2">
          Detectado enquanto o sistema ainda aprendia o que é normal neste computador, então
          você não foi notificado. Nas primeiras horas quase tudo parece novo — inclusive
          programas que sempre estiveram aqui. Fica registrado para você conferir quando
          quiser.
        </p>
      )}

      <TrustNote anomaly={anomaly} />

      <div className="mt-6 border-t border-hairline pt-5">
        {lead ? (
          <>
            <p className="max-w-prose text-md leading-relaxed text-fg">{lead}</p>

            <div className={`mt-5 max-w-prose border-l-2 pl-4 ${urgency.borderStrong}`}>
              <p className="channel-label">Urgência</p>
              <p className={`mt-1 text-sm leading-relaxed ${urgency.text}`}>{verdict}</p>
            </div>

            <VerificationTag anomaly={anomaly} />

            <div className="mt-5 flex flex-wrap items-center gap-x-3 gap-y-2">
              {exp && <LanguageLevelSwitch anomaly={anomaly} current={level} onVariant={(l, v) => { setLevel(l); setVariant(v); }} />}
              {exp && <RatingButtons anomaly={anomaly} />}
              <span className="ml-auto flex items-center gap-3">
                <VerificationBadge verification={exp?.verification} />
                <DestinationTag destination={exp?.data_destination} provider={shown?.model_used} />
              </span>
            </div>

            <Feedback anomaly={anomaly} onChange={setAnomaly} />
          </>
        ) : (
          <EmptyState
            title="A explicação em linguagem simples ainda não chegou"
            body="Os números da detecção, mais abaixo, já estão completos. A análise escrita depende do serviço de IA."
            action={<Button variant="primary" loading={regenerating} loadingLabel="Gerando..." onClick={handleRegenerate}>Gerar a explicação agora</Button>}
          />
        )}
      </div>

      {exp?.counterfactual && !anomaly.is_resolved && (
        <div className="mt-8">
          <CounterfactualCard cf={exp.counterfactual} />
        </div>
      )}

      {machine && !anomaly.is_resolved && (
        <Section className="mt-9" title="Agir agora" description="Ações executadas no próprio computador, com um clique">
          <AnomalyActions anomaly={anomaly} machine={machine} />
        </Section>
      )}

      {/* Depois da ação, a promessa do cartão "e se eu fechar?" é conferida
          contra a leitura seguinte. */}
      <PredictionCheck anomalyId={anomaly.id} />

      {(shown?.recommendations?.length ?? 0) > 0 && (
        <Section className="mt-9" title="O que fazer, passo a passo" description="Marque o que já tentou — o sistema sugere o próximo">
          {variant ? (
            <ol className="space-y-4">
              {variant.recommendations.map((s: string, i: number) => (
                <li key={i} className="flex gap-4">
                  <span className="tnum font-mono text-micro text-fg-3">{i + 1}</span>
                  <p className="max-w-prose text-sm leading-relaxed text-fg-2">{s}</p>
                </li>
              ))}
            </ol>
          ) : (
            <AdaptiveSteps anomaly={anomaly} onChange={setAnomaly} />
          )}
        </Section>
      )}

      {incident && incident.chain && incident.chain.nodes.length > 1 && (
        <Section className="mt-9" title="Como isso se encadeou" description="Sintomas que aconteceram juntos, ligados por causa e efeito">
          <IncidentChain incident={incident} />
        </Section>
      )}

      {chart && context.length > 1 && (
        <Section className="mt-9" title="O momento em que aconteceu" description="A linha vertical marca o instante da detecção">
          <MetricChart
            metrics={context}
            dataKey={chart.key}
            label={chart.label}
            term={chart.term}
            threshold={chart.threshold}
            markAt={anomaly.detected_at}
            unit={chart.key === "net_connections" ? "" : "%"}
            domain={chart.key === "net_connections" ? [0, Math.max(...context.map((m) => m.net_connections ?? 0)) + 10] : undefined}
          />
        </Section>
      )}

      <Section
        className="mt-9"
        title="Reveja o que aconteceu"
        description="Percorra a linha do tempo e veja quem estava consumindo a cada instante"
      >
        <Replay anomaly={anomaly} blackboxId={blackboxId} />
      </Section>

      {(shown?.possible_causes?.length ?? 0) > 0 && (
        <Section className="mt-9" title="Por que isso pode ter acontecido" description="O sistema ordena por probabilidade">
          <RankedCauses causes={shown!.possible_causes!} />
        </Section>
      )}

      <div className="mt-10">
        {shown?.detailed_explanation && (
          <Disclosure title="Entenda em detalhe" note="a análise completa">
            <p className="max-w-prose whitespace-pre-line text-sm leading-relaxed text-fg-2">{shown.detailed_explanation}</p>
          </Disclosure>
        )}

        <MlContributions anomaly={anomaly} />

        <Disclosure title="Dados da leitura" note="números da detecção">
          <Panel className="px-4 py-2">
            <DataList>
              {anomaly.affected_metrics && Object.keys(anomaly.affected_metrics).length > 0 ? (
                Object.entries(anomaly.affected_metrics)
                  .filter(([key, val]) => key !== "_behavior" && typeof val !== "object")
                  .map(([key, val]) => (
                    <DataRow
                      key={key}
                      label={key.replace(/_/g, " ").replace(/^./, (c) => c.toUpperCase())}
                      value={typeof val === "number" ? (key.includes("percent") || key.includes("cpu") || key.includes("mem") ? `${val.toFixed(1)}%` : val.toFixed(1)) : String(val)}
                    />
                  ))
              ) : (
                <DataRow label="Métricas" value="nenhuma registrada" />
              )}
              {processName(anomaly) && <DataRow label="Programa responsável" value={processName(anomaly)!} mono />}
              {anomaly.anomaly_score != null && (
                <DataRow label="Desvio do padrão" value={anomaly.anomaly_score.toFixed(4)} hint={<Explain term="score" />} />
              )}
            </DataList>
          </Panel>
        </Disclosure>

        <Disclosure title="Precisa de ajuda de alguém?" note="link para o técnico">
          <div className="space-y-3">
            <p className="max-w-prose text-sm leading-relaxed text-fg-2">
              Gere um link temporário e somente leitura com tudo deste aviso — números, explicação, o que já foi
              tentado — para mandar a quem vai te ajudar. Quem receber não precisa de conta.
            </p>
            <div className="flex flex-wrap gap-2">
              <ShareButton anomalyId={anomaly.id} />
              {/*
                Imprimir resolve o caso em que o link não serve: anexar a um
                chamado, entregar impresso, guardar um PDF que não depende do
                servidor estar no ar. O CSS de impressão já abre os blocos
                recolhidos e tira menu e botões da folha.
              */}
              <Button variant="quiet" onClick={() => window.print()}>
                Imprimir ou salvar em PDF
              </Button>
            </div>
          </div>
        </Disclosure>
      </div>

      <div className="mt-8 flex flex-wrap gap-2 border-t border-hairline pt-5">
        <Button variant={anomaly.is_resolved ? "secondary" : "quiet"} onClick={handleResolveToggle}>
          {anomaly.is_resolved ? "Reabrir aviso" : "Só marcar como resolvido"}
        </Button>
        {exp && <Button variant="quiet" loading={regenerating} loadingLabel="Gerando..." onClick={handleRegenerate}>Gerar nova explicação</Button>}
      </div>
    </div>
  );
}

/**
 * O que se sabe do programa acusado, na hora em que a pessoa está decidindo
 * se aquilo é um vírus.
 *
 * O painel tinha todos esses dados (assinatura, fabricante, em quantos
 * computadores o executável aparece) e não mostrava nenhum justamente aqui.
 * Sem isso, "processo consumindo recursos" soa igual para o antivírus da
 * pessoa e para um minerador.
 */
function TrustNote({ anomaly }: { anomaly: Anomaly }) {
  const behavior = (anomaly.affected_metrics as any)?._behavior;
  const reasons: string[] = behavior?.confianca_motivos || [];
  if (!reasons.length) return null;
  const seguranca = behavior?.confianca >= 3;
  return (
    <p className="mt-4 max-w-prose border-l-2 border-edge pl-4 text-xs leading-relaxed text-fg-2">
      <span className="text-fg">Sobre este programa:</span> {reasons.join(", ")}.
      {seguranca && " Programas de segurança varrem arquivos e baixam atualizações o tempo todo — é o trabalho deles, e se parece com o de um vírus."}
    </p>
  );
}

/** Contribuição de cada grupo de medidas para a nota do modelo. */
function MlContributions({ anomaly }: { anomaly: Anomaly }) {
  const behavior = (anomaly.affected_metrics as any)?._behavior;
  const contributions = behavior?.contributions || behavior?.ml_contributions;
  if (!contributions?.length) return null;
  return (
    <Disclosure title="O que o modelo achou estranho" note="peso de cada medida no desvio">
      <div className="space-y-2.5">
        {contributions.map((c: any) => (
          <div key={c.group} className="flex items-center gap-3">
            <span className="w-40 flex-shrink-0 truncate text-sm text-fg-2" title={c.label}>{c.label}</span>
            <div className="h-1.5 flex-1 overflow-hidden rounded-full bg-sunken">
              <div className="h-full bg-fg-3" style={{ width: `${Math.min(c.percent, 100)}%` }} />
            </div>
            <span className="tnum w-12 flex-shrink-0 text-right font-mono text-xs text-fg">{c.percent.toFixed(0)}%</span>
          </div>
        ))}
        <p className="pt-1 text-xs text-fg-3">
          A leitura fugiu do padrão desta máquina; estas medidas foram as que mais pesaram nessa conclusão.
        </p>
      </div>
    </Disclosure>
  );
}
