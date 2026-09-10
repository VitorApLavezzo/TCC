import { useState, useEffect, useRef, useCallback } from "react";
import { useParams, useNavigate } from "react-router-dom";
import { anomaliesApi, explanationsApi, machinesApi, metricsApi, errorMessage } from "../services/api";
import { Anomaly, Metric, ANOMALY_TYPE_LABELS } from "../types";
import { Severity } from "../components/ui/Badge";
import { Section, Panel, DataList, DataRow, StatusDot } from "../components/ui/Layout";
import { Button, TextButton } from "../components/ui/Button";
import { Disclosure } from "../components/ui/Disclosure";
import { ActionSteps, RankedCauses } from "../components/AnomalyExplanation";
import { Explain } from "../components/ui/Explain";
import { Skeleton } from "../components/ui/Skeleton";
import { EmptyState } from "../components/ui/EmptyState";
import { MetricChart } from "../components/charts/MetricChart";
import { useToast } from "../components/ui/Toast";
import { ANOMALY_TYPE_HINTS, SEVERITY_URGENCY } from "../lib/glossary";
import { health, LEVEL_CLASS, THRESHOLDS } from "../lib/health";
import { format } from "date-fns";
import { ptBR } from "date-fns/locale";
import { ArrowLeft } from "lucide-react";

/** Qual métrica ilustra melhor cada tipo de anomalia. */
const CPU = { key: "cpu_percent" as keyof Metric, label: "Processador", term: "cpu", threshold: THRESHOLDS.cpu.warn };
const MEM = { key: "mem_percent" as keyof Metric, label: "Memória", term: "memoria", threshold: THRESHOLDS.memory.warn };
const NET = { key: "net_connections" as keyof Metric, label: "Conexões de rede", term: "conexoes" };

const CHART_FOR: Record<string, { key: keyof Metric; label: string; term: string; threshold?: number }> = {
  high_cpu: CPU,
  cpu_loop: CPU,
  resource_exhaustion: CPU,
  high_memory: MEM,
  memory_leak: MEM,
  disk_full: { key: "disk_percent", label: "Disco", term: "disco", threshold: THRESHOLDS.disk.warn },
  network_spike: NET,
  ddos_indicator: NET,
};

/**
 * O detalhe de um aviso.
 *
 * A tela responde, nesta ordem: o que houve, se é urgente, o que fazer, a
 * prova, por que aconteceu. O aprofundamento fica fechado.
 *
 * A ordem importa porque a IA escreve cerca de três mil caracteres por aviso.
 * Empilhados com o mesmo peso, ninguém lê nenhum — e o primeiro passo prático
 * ficava depois de dois parágrafos longos e de um gráfico.
 */
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
  const chart = CHART_FOR[anomaly.anomaly_type];

  /*
   * Uma frase de urgência, não três.
   *
   * Antes o selo de severidade, a frase fixa por severidade e a justificativa
   * da IA apareciam juntas e podiam se contradizer na mesma tela: o selo dizia
   * "Alta" enquanto a IA dizia "severidade baixa na prática". Quando a IA
   * justificou, é a dela que vale — ela comparou com o histórico desta
   * máquina. A frase fixa entra só enquanto a análise não chegou.
   */
  const verdict = exp?.severity_justification || SEVERITY_URGENCY[anomaly.severity];

  /*
   * A dica fixa do tipo só aparece enquanto não há resumo da IA. Com as duas
   * na tela, ela repetia — e às vezes contradizia — o texto que a IA escreveu
   * olhando os números reais desta máquina.
   */
  const lead = exp?.summary || ANOMALY_TYPE_HINTS[anomaly.anomaly_type];

  const urgency =
    anomaly.severity === "critical"
      ? LEVEL_CLASS.crit
      : anomaly.severity === "low"
        ? LEVEL_CLASS.unknown
        : LEVEL_CLASS.warn;

  const resolveButton = (
    <Button variant={anomaly.is_resolved ? "secondary" : "primary"} onClick={handleResolve}>
      {anomaly.is_resolved ? "Reabrir aviso" : "Marcar como resolvido"}
    </Button>
  );

  return (
    <div className="max-w-3xl">
      <TextButton onClick={() => navigate("/anomalies")} className="inline-flex items-center gap-1.5 text-fg-2">
        <ArrowLeft size={12} aria-hidden="true" />
        Todos os avisos
      </TextButton>

      <header className="mt-6">
        {/*
          Sobrancelha de detecção: o mesmo losango da fita de eventos, agora em
          tamanho de título. Diz de saída que isto é um evento com hora marcada.
        */}
        <p className="flex items-center gap-2">
          <span className="h-[7px] w-[7px] rotate-45 bg-accent" aria-hidden="true" />
          <span className="channel-label">Detectado</span>
          <span className="tnum font-mono text-micro text-fg-2">
            {format(new Date(anomaly.detected_at), "dd/MM/yyyy 'às' HH:mm:ss", { locale: ptBR })}
          </span>
        </p>

        <div className="mt-2.5 flex flex-wrap items-baseline gap-x-4 gap-y-1">
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

        {(machineName || anomaly.responsible_process) && (
          <p className="mt-2 flex flex-wrap items-center gap-x-4 gap-y-1 text-xs text-fg-3">
            {machineName && <span>{machineName}</span>}
            {anomaly.responsible_process && <span className="font-mono text-fg-2">{anomaly.responsible_process}</span>}
          </p>
        )}
      </header>

      <div className="mt-6 border-t border-hairline pt-5">
        {lead ? (
          <>
            {/*
              A resposta. É o único parágrafo em corpo maior da tela: quem ler
              só isto e a linha de urgência abaixo já sabe o que houve e se
              precisa agir hoje.
            */}
            <p className="max-w-prose text-md leading-relaxed text-fg">{lead}</p>

            {/*
              O veredito precisa de presença: é ele que responde "é grave?".
              A versão anterior usava uma barra de 30% de opacidade e, em
              severidade baixa, ficava indistinguível de um parágrafo
              indentado por acidente. Agora a barra é cheia e o rótulo diz o
              que a frase é, para ela não se confundir com mais um texto.
            */}
            <div className={`mt-5 max-w-prose border-l-2 pl-4 ${urgency.borderStrong}`}>
              <p className="channel-label">Urgência</p>
              <p className={`mt-1 text-sm leading-relaxed ${urgency.text}`}>{verdict}</p>
            </div>

            <div className="mt-5 flex flex-wrap items-center gap-2">
              {resolveButton}
              {exp && (
                <Button variant="quiet" loading={regenerating} loadingLabel="Gerando..." onClick={handleRegenerate}>
                  Gerar nova explicação
                </Button>
              )}
              {exp?.model_used && <span className="ml-auto text-micro text-fg-3">{exp.model_used}</span>}
            </div>
          </>
        ) : (
          <>
            <EmptyState
              title="A explicação em linguagem simples ainda não chegou"
              body="Os números da detecção, mais abaixo, já estão completos. A análise escrita depende do serviço de IA, que pode estar ocupado ou desligado."
              action={
                <Button variant="primary" loading={regenerating} loadingLabel="Gerando..." onClick={handleRegenerate}>
                  Gerar a explicação agora
                </Button>
              }
            />
            <div className="mt-4">{resolveButton}</div>
          </>
        )}
      </div>

      {/* O acionável vem antes da prova e antes do aprofundamento. */}
      {exp?.recommendations && exp.recommendations.length > 0 && (
        <Section className="mt-9" title="O que fazer agora" description="Na ordem, do mais simples para o mais avançado">
          <ActionSteps steps={exp.recommendations} />
        </Section>
      )}

      {/* Uma pausa visual no meio do texto, e a prova do que foi dito. */}
      {chart && context.length > 1 && (
        <Section
          className="mt-9"
          title="O momento em que aconteceu"
          description="A linha vertical marca o instante da detecção"
        >
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

      {exp?.possible_causes && exp.possible_causes.length > 0 && (
        <Section className="mt-9" title="Por que isso pode ter acontecido" description="O sistema ordena por probabilidade">
          <RankedCauses causes={exp.possible_causes} />
        </Section>
      )}

      {/*
        Segundo nível: o texto longo da IA e a leitura crua. Nada foi removido
        — mudou o momento em que aparece. Quem quer o detalhe abre; quem quer
        resolver o problema não precisa atravessar mil e trezentos caracteres
        para chegar ao primeiro passo.
      */}
      <div className="mt-10">
        {exp?.detailed_explanation && (
          <Disclosure title="Entenda em detalhe" note="a análise completa">
            <p className="max-w-prose whitespace-pre-line text-sm leading-relaxed text-fg-2">
              {exp.detailed_explanation}
            </p>
          </Disclosure>
        )}

        {exp && !exp.possible_causes?.length && (
          <Disclosure title="Por que isso pode ter acontecido" note="ainda analisando">
            <p className="text-sm text-fg-3">Analisando as causas. Esta parte atualiza sozinha quando a IA terminar.</p>
          </Disclosure>
        )}

        <Disclosure title="Dados da leitura" note="números da detecção">
          <Panel className="px-4 py-2">
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
        </Disclosure>
      </div>
    </div>
  );
}
