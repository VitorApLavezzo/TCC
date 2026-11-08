import { useCallback, useEffect, useState } from "react";
import { isNotFound } from "../lib/http";
import { useParams, useNavigate, useSearchParams } from "react-router-dom";
import {
  insightsApi, reportsApi, reputationApi, accountApi, machinesExtraApi, machinesApi, anomaliesApi, errorMessage,
} from "../services/api";
import { Anomaly, ANOMALY_TYPE_LABELS, Machine } from "../types";
import { PageHeader, Section, Panel, DataList, DataRow, StatusDot } from "../components/ui/Layout";
import { Severity } from "../components/ui/Badge";
import { FreshnessTag } from "../components/FreshnessTag";
import { decimal, pluralize } from "../lib/format";
import { statusByMachine } from "../lib/machineStatus";
import { useDocumentTitle } from "../lib/title";
import { Button, TextButton } from "../components/ui/Button";
import { Skeleton } from "../components/ui/Skeleton";
import { EmptyState } from "../components/ui/EmptyState";
import { LoadError } from "../components/ui/LoadError";
import { useToast } from "../components/ui/Toast";
import { format } from "date-fns";
import { ptBR } from "date-fns/locale";
import { ArrowLeft } from "lucide-react";
import { ModelHealth } from "../components/reliability/ModelHealth";
import { HardwareRisk } from "../components/reliability/HardwareRisk";
import { Timeline } from "../components/reliability/Timeline";
import { ActivityLabelControl } from "../components/machines/ActivityLabelControl";

const TABS = [
  { id: "resumo", label: "Resumo" },
  { id: "saude", label: "Saúde e previsões" },
  { id: "diario", label: "Diário e mudanças" },
  { id: "programas", label: "Programas e energia" },
  { id: "privacidade", label: "Privacidade" },
];

/** Endereços das abas antigas continuam abrindo o conteúdo certo. */
const LEGACY_TABS: Record<string, string> = {
  linha: "resumo",
  previsoes: "saude",
  upgrade: "saude",
  mudancas: "diario",
  energia: "programas",
};

function SummaryTab({ machineId, machine }: { machineId: number; machine: Machine | null }) {
  const navigate = useNavigate();
  // O id vem do endereço, não do computador carregado: sem isso a primeira
  // busca saía sem filtro e, se o computador não carregasse, a aba ficava em branco.
  const { data, loading, error, reload } = useAsync<Anomaly[]>(
    () => anomaliesApi.list({ machine_id: machineId, hours: 720, unresolved_only: true, limit: 500 }),
    [machineId]
  );
  const status = data ? statusByMachine(data)[machineId] ?? { open: 0, worst: null } : null;

  return (
    <div className="space-y-8">
      {loading ? (
        <Skeleton className="h-24 w-full rounded-panel" />
      ) : error ? (
        <LoadError what="os avisos deste computador" onRetry={reload} />
      ) : (
        status && (
          <Panel className="flex flex-wrap items-center justify-between gap-4 p-5">
            <div className="min-w-0 space-y-2">
              {status.open === 0 ? (
                <p className="flex items-center gap-2 text-md font-medium text-fg">
                  <StatusDot tone="ok" />
                  Nenhum aviso em aberto
                </p>
              ) : (
                <p className="flex flex-wrap items-center gap-2 text-md font-medium text-fg">
                  <Severity severity={status.worst!.severity} />
                  {pluralize(status.open, "aviso em aberto", "avisos em aberto")}
                </p>
              )}
              {status.worst && (
                <p className="text-sm text-fg-2">
                  O mais grave: {ANOMALY_TYPE_LABELS[status.worst.anomaly_type] ?? status.worst.anomaly_type}
                </p>
              )}
              {machine && (
                <FreshnessTag lastMetricAt={machine.last_seen} wsStatus="idle" paused={!machine.is_active} />
              )}
            </div>
            <div className="flex flex-wrap gap-2">
              {status.worst && (
                <Button variant="primary" onClick={() => navigate(`/anomalies/${status.worst!.id}`)}>
                  Ver o que aconteceu
                </Button>
              )}
              <Button variant="secondary" onClick={() => navigate(`/?computador=${machineId}`)}>
                Ver ao vivo no painel
              </Button>
            </div>
          </Panel>
        )
      )}
      <Timeline machineId={machineId} />
    </div>
  );
}

function HealthTab({ machineId }: { machineId: number }) {
  return (
    <div className="space-y-8">
      <Section title="Previsões" description="Para onde o disco, a bateria e a memória estão indo">
        <ForecastTab machineId={machineId} />
      </Section>
      <HardwareRisk machineId={machineId} />
      <Section title="Vale trocar alguma peça?" description="Pelo histórico de avisos deste computador">
        <UpgradeTab machineId={machineId} />
      </Section>
      <ModelHealth machineId={machineId} />
    </div>
  );
}

export function MachineDetail() {
  const { id } = useParams<{ id: string }>();
  const machineId = Number(id);
  const navigate = useNavigate();
  const [params, setParams] = useSearchParams();
  const requested = params.get("aba") || "resumo";
  const tab = LEGACY_TABS[requested] ?? (TABS.some((t) => t.id === requested) ? requested : "resumo");
  const [machine, setMachine] = useState<Machine | null>(null);
  const [notFound, setNotFound] = useState(false);
  useDocumentTitle(machine?.name);

  useEffect(() => {
    setNotFound(false);
    machinesApi
      .get(machineId)
      .then((r) => setMachine(r.data))
      .catch((err) => setNotFound(isNotFound(err)));
  }, [machineId]);

  const setTab = (t: string) => setParams({ aba: t }, { replace: true });

  // Setas trocam de aba, como em qualquer lista de abas: só a ativa entra
  // na ordem do Tab, as outras se alcançam pelas setas.
  const onTabKey = (e: React.KeyboardEvent) => {
    if (e.key !== "ArrowRight" && e.key !== "ArrowLeft") return;
    const i = TABS.findIndex((t) => t.id === tab);
    const next = TABS[(i + (e.key === "ArrowRight" ? 1 : TABS.length - 1)) % TABS.length];
    setTab(next.id);
    requestAnimationFrame(() => document.getElementById(`aba-${next.id}`)?.focus());
  };

  if (notFound) {
    return (
      <div className="max-w-3xl">
        <EmptyState
          title="Este computador não existe mais"
          body="Ele pode ter sido removido da sua conta."
          action={<Button variant="primary" onClick={() => navigate("/machines")}>Voltar para os computadores</Button>}
        />
      </div>
    );
  }

  return (
    <div className="space-y-6">
      {/* A página mora em Computadores (é o item aceso no menu): voltar leva
          para lá, e não para o Painel. */}
      <TextButton onClick={() => navigate("/machines")} className="inline-flex items-center gap-1.5 text-fg-2">
        <ArrowLeft size={12} aria-hidden="true" />
        Computadores
      </TextButton>
      <PageHeader
        title={machine?.name ?? "Computador"}
        description={machine?.os_pretty ?? machine?.os_type ?? undefined}
        aside={machine ? <ActivityLabelControl machineId={machineId} /> : undefined}
      />

      {/* Rola de lado no celular em vez de quebrar em várias linhas. */}
      <div
        role="tablist"
        aria-label="Seções do computador"
        onKeyDown={onTabKey}
        className="-mx-4 flex gap-1 overflow-x-auto border-b border-hairline px-4 sm:mx-0 sm:px-0"
      >
        {TABS.map((t) => (
          <button
            key={t.id}
            id={`aba-${t.id}`}
            type="button"
            role="tab"
            aria-selected={tab === t.id}
            tabIndex={tab === t.id ? 0 : -1}
            onClick={() => setTab(t.id)}
            className={`relative flex-shrink-0 whitespace-nowrap px-3 py-2 text-sm transition-colors ${
              tab === t.id ? "font-medium text-fg" : "text-fg-3 hover:text-fg-2"
            }`}
          >
            {t.label}
            {tab === t.id && <span className="absolute inset-x-2 -bottom-px h-0.5 rounded-full bg-accent" />}
          </button>
        ))}
      </div>

      <div role="tabpanel" aria-labelledby={`aba-${tab}`}>
        {tab === "resumo" && <SummaryTab machineId={machineId} machine={machine} />}
        {tab === "saude" && <HealthTab machineId={machineId} />}
        {tab === "diario" && (
          <div className="space-y-10">
            <DiaryTab machineId={machineId} />
            <Section title="Instalações e atualizações" description="O que mudou no sistema e o efeito que teve">
              <ChangesTab machineId={machineId} />
            </Section>
          </div>
        )}
        {tab === "programas" && (
          <div className="space-y-10">
            <Section title="Programas instalados" description="Com a reputação de cada um">
              <ProgramsTab machineId={machineId} />
            </Section>
            <Section title="Energia" description="Quanto este computador consome e custa por mês">
              <EnergyTab machineId={machineId} />
            </Section>
          </div>
        )}
        {tab === "privacidade" && <PrivacyTab machineId={machineId} machine={machine} onChange={setMachine} />}
      </div>
    </div>
  );
}

/** Busca de uma aba. `error` separa "não carregou" de "não tem nada". */
function useAsync<T>(fn: () => Promise<{ data: T }>, deps: any[] = []) {
  const [data, setData] = useState<T | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(false);
  const run = useCallback(() => {
    setLoading(true);
    setError(false);
    fn()
      .then((r) => setData(r.data))
      .catch(() => {
        setData(null);
        setError(true);
      })
      .finally(() => setLoading(false));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, deps);
  useEffect(run, [run]);
  return { data, loading, error, reload: run };
}

function Loading() {
  return <div className="space-y-3"><Skeleton className="h-24 w-full rounded-panel" /><Skeleton className="h-24 w-full rounded-panel" /></div>;
}

function Big({ title, sentence, tone }: { title: string; sentence?: string; tone?: "warn" | "crit" | "ok" }) {
  const color = tone === "crit" ? "text-crit" : tone === "warn" ? "text-warn" : tone === "ok" ? "text-ok" : "text-fg";
  return (
    <div className="rounded-panel border border-hairline bg-surface px-5 py-4">
      <p className={`text-md font-medium ${color}`}>{title}</p>
      {sentence && <p className="mt-1.5 max-w-prose text-sm leading-relaxed text-fg-2">{sentence}</p>}
    </div>
  );
}

function ForecastTab({ machineId }: { machineId: number }) {
  const { data, loading, error, reload } = useAsync<any>(() => insightsApi.forecast(machineId), [machineId]);
  if (loading) return <Loading />;
  if (error) return <LoadError what="as previsões" onRetry={reload} />;
  if (!data) return <EmptyState title="Sem previsões ainda" body="São precisas algumas leituras para projetar tendências." />;
  return (
    <div className="space-y-4">
      {data.disk?.ready ? (
        <Big title="Disco" sentence={data.disk.sentence} tone={data.disk.eta_days && data.disk.eta_days <= 7 ? "warn" : undefined} />
      ) : (
        <Big title="Disco" sentence={data.disk?.reason} />
      )}
      {data.battery?.ready ? (
        <Big title="Bateria" sentence={data.battery.sentence} tone={data.battery.health_now < 70 ? "warn" : "ok"} />
      ) : data.battery?.reason ? (
        <Big title="Bateria" sentence={data.battery.reason} />
      ) : null}
      {data.memory_leaks?.map((m: any) => (
        <Big key={m.anomaly_id} title={`Vazamento em ${m.process}`} sentence={m.sentence} tone="crit" />
      ))}
    </div>
  );
}

function DiaryTab({ machineId }: { machineId: number }) {
  const toast = useToast();
  const { data, loading, error, reload } = useAsync<any>(() => reportsApi.list(machineId), [machineId]);
  const [gen, setGen] = useState(false);
  const generate = async () => {
    setGen(true);
    try {
      await reportsApi.generate(machineId);
      reload();
    } catch (err) {
      toast.error(errorMessage(err, "Ainda não há dados da semana passada."));
    } finally {
      setGen(false);
    }
  };
  if (loading) return <Loading />;
  if (error) return <LoadError what="os diários" onRetry={reload} />;
  const reports = data?.reports ?? [];
  return (
    <div className="space-y-5">
      <div className="flex justify-end">
        <Button variant="secondary" loading={gen} onClick={generate}>Gerar diário da última semana</Button>
      </div>
      {reports.length === 0 ? (
        <EmptyState title="Nenhum diário ainda" body="Todo início de semana o sistema escreve um resumo do que aconteceu. Você também pode gerar agora." />
      ) : (
        reports.map((r: any) => (
          <article key={r.id} className="rounded-panel border border-hairline bg-surface px-5 py-4">
            <p className="channel-label">
              {r.period_start && r.period_end &&
                `${format(new Date(r.period_start), "dd/MM", { locale: ptBR })} – ${format(new Date(r.period_end), "dd/MM", { locale: ptBR })}`}
            </p>
            <p className="mt-2 max-w-prose whitespace-pre-line text-sm leading-relaxed text-fg">{r.narrative}</p>
            {r.highlights?.length > 0 && (
              <ul className="mt-3 space-y-1">
                {r.highlights.map((h: string, i: number) => (
                  <li key={i} className="flex gap-2 text-xs text-fg-2"><span className="text-fg-3">•</span>{h}</li>
                ))}
              </ul>
            )}
            {r.model_used && <p className="mt-2 text-micro text-fg-3">{r.model_used}</p>}
          </article>
        ))
      )}
    </div>
  );
}

function EnergyTab({ machineId }: { machineId: number }) {
  const { data, loading, error, reload } = useAsync<any>(() => insightsApi.energy(machineId), [machineId]);
  if (loading) return <Loading />;
  if (error) return <LoadError what="o consumo de energia" onRetry={reload} />;
  if (!data?.ready) return <EmptyState title="Sem estimativa ainda" body={data?.reason ?? "São precisas algumas leituras."} />;
  return (
    <div className="space-y-4">
      <Big title={data.sentence} />
      <Panel className="px-4 py-2">
        <DataList>
          <DataRow label="Consumo no mês (estimado)" value={`${data.monthly_kwh} kWh`} />
          <DataRow label="Custo no mês" value={data.monthly_cost != null ? `R$ ${decimal(data.monthly_cost, 2)}` : "--"} />
          <DataRow label="CO₂ no mês" value={`${data.monthly_co2_kg} kg`} />
          <DataRow label="Parte medida (não estimada)" value={`${data.measured_share_pct}%`} />
        </DataList>
      </Panel>
      {data.waste?.sentence && <Big title="Desperdício" sentence={data.waste.sentence} tone="warn" />}
      {data.waste?.sleep_blockers?.length > 0 && (
        <Panel className="px-4 py-3">
          <p className="channel-label mb-1.5">Impedindo o computador de dormir</p>
          <ul className="space-y-1">
            {data.waste.sleep_blockers.map((b: string, i: number) => (
              <li key={i} className="font-mono text-micro text-fg-3">{b}</li>
            ))}
          </ul>
        </Panel>
      )}
      {data.top_processes?.length > 0 && (
        <Panel className="px-4 py-2">
          <DataList>
            {data.top_processes.map((p: any) => (
              <DataRow key={p.name} label={p.name} value={`${p.kwh} kWh · R$ ${p.cost != null ? decimal(p.cost, 2) : "--"}`} mono />
            ))}
          </DataList>
        </Panel>
      )}
    </div>
  );
}

function ChangesTab({ machineId }: { machineId: number }) {
  const { data, loading, error, reload } = useAsync<any>(() => insightsApi.changes(machineId), [machineId]);
  if (loading) return <Loading />;
  if (error) return <LoadError what="as mudanças no sistema" onRetry={reload} />;
  const changes = data?.changes ?? [];
  if (changes.length === 0) return <EmptyState title="Nada mudou por aqui" body="Instalações, atualizações e drivers novos aparecem nesta linha do tempo, com o efeito que tiveram." />;
  const KIND: Record<string, string> = {
    installed: "Instalado", removed: "Removido", updated: "Atualizado", os_update: "Sistema atualizado",
    hotfix: "Atualização do Windows", driver_update: "Driver atualizado", agent_update: "Agente atualizado",
  };
  return (
    <ul className="divide-y divide-hairline border-y border-hairline">
      {changes.map((c: any) => (
        <li key={c.id} className="flex gap-3 py-3">
          <span className="tnum w-14 flex-shrink-0 pt-0.5 font-mono text-micro text-fg-3">
            {format(new Date(c.detected_at), "dd/MM", { locale: ptBR })}
          </span>
          <div className="min-w-0">
            <p className="text-sm text-fg">
              <span className="text-fg-3">{KIND[c.kind] ?? c.kind}:</span> {c.name}
              {c.version_to && <span className="ml-1 font-mono text-xs text-fg-3">{c.version_from ? `${c.version_from} → ` : ""}{c.version_to}</span>}
            </p>
            {c.impact?.sentence && <p className="mt-1 max-w-prose text-xs leading-relaxed text-warn">{c.impact.sentence}</p>}
          </div>
        </li>
      ))}
    </ul>
  );
}

function UpgradeTab({ machineId }: { machineId: number }) {
  const { data, loading, error, reload } = useAsync<any>(() => insightsApi.upgrade(machineId), [machineId]);
  if (loading) return <Loading />;
  if (error) return <LoadError what="as recomendações de peças" onRetry={reload} />;
  if (!data?.ready) return <EmptyState title="Sem recomendações ainda" body={data?.reason ?? "São precisos alguns dias de uso."} />;
  const recs = data.recommendations ?? [];
  if (recs.length === 0) return <EmptyState title="Nenhuma troca recomendada" body="Pelo histórico, as peças dão conta do seu uso. Nada a trocar por ora." />;
  return (
    <div className="space-y-3">
      <p className="text-sm text-fg-3">Com base nos avisos dos últimos {data.period_days} dias:</p>
      {recs.map((r: any, i: number) => (
        <div key={i} className="rounded-panel border border-hairline bg-surface px-5 py-4">
          <div className="flex items-baseline justify-between gap-3">
            <p className="text-md font-medium text-fg">{r.title}</p>
            <span className="tnum flex-shrink-0 font-mono text-xs text-accent">evitaria ~{r.impact_pct}%</span>
          </div>
          <p className="mt-1.5 max-w-prose text-sm leading-relaxed text-fg-2">{r.sentence}</p>
        </div>
      ))}
    </div>
  );
}

function ProgramsTab({ machineId }: { machineId: number }) {
  const { data, loading, error, reload } = useAsync<any>(() => reputationApi.programs(machineId), [machineId]);
  if (loading) return <Loading />;
  if (error) return <LoadError what="a lista de programas" onRetry={reload} />;
  const programs = data?.programs ?? [];
  if (programs.length === 0)
    return (
      <EmptyState
        title="Nenhum programa listado ainda"
        body="A lista aparece depois que o agente faz o primeiro inventário deste computador."
      />
    );
  const tone: Record<string, string> = {
    suspeito: "text-crit", "comum e sem queixas": "text-ok", raro: "text-warn", "sem opinião formada": "text-fg-3",
  };
  return (
    <ul className="divide-y divide-hairline border-y border-hairline">
      {programs.map((p: any) => (
        <li key={`${p.name}-${p.exe}`} className="flex items-start justify-between gap-4 py-3">
          <div className="min-w-0">
            <p className="truncate text-sm text-fg">{p.name}</p>
            {p.publisher && <p className="truncate text-xs text-fg-3">{p.publisher}</p>}
            {p.reputation?.sentence && <p className="mt-0.5 max-w-prose text-xs text-fg-3">{p.reputation.sentence}</p>}
          </div>
          <span className="flex flex-shrink-0 flex-col items-end gap-0.5">
            {p.reputation && <span className={`text-xs ${tone[p.reputation.verdict] ?? "text-fg-3"}`}>{p.reputation.verdict}</span>}
            <span className="text-micro text-fg-3">{p.signed === "signed" ? "assinado" : p.signed === "unsigned" ? "sem assinatura" : ""}</span>
          </span>
        </li>
      ))}
    </ul>
  );
}

function PrivacyTab({ machineId, machine, onChange }: { machineId: number; machine: Machine | null; onChange: (m: Machine) => void }) {
  const toast = useToast();
  const { data, loading, error, reload } = useAsync<any>(() => accountApi.privacy(machineId), [machineId]);
  const [saving, setSaving] = useState(false);

  const setPrivacy = async (value: string) => {
    setSaving(true);
    try {
      const res = await machinesExtraApi.setPrivacy(machineId, value);
      onChange(res.data);
      toast.success("Preferência de privacidade salva.");
    } catch (err) {
      toast.error(errorMessage(err));
    } finally {
      setSaving(false);
    }
  };

  if (loading) return <Loading />;
  if (error) return <LoadError what="as preferências de privacidade" onRetry={reload} />;
  const current = machine?.ai_privacy ?? data?.ai_privacy ?? "any";

  return (
    <div className="space-y-6">
      <Section title="Como a IA pode usar os dados deste computador">
        <div className="space-y-2">
          {Object.entries(data?.ai_privacy_options ?? {}).map(([value, label]) => (
            <label key={value} className={`flex cursor-pointer items-start gap-3 rounded-panel border px-4 py-3 transition-colors ${current === value ? "border-accent bg-accent/5" : "border-hairline hover:border-edge"}`}>
              <input type="radio" checked={current === value} disabled={saving} onChange={() => setPrivacy(value)} className="mt-1 accent-accent" />
              <span className="text-sm text-fg-2">{label as string}</span>
            </label>
          ))}
        </div>
      </Section>

      <Section title="O que foi enviado sobre este computador">
        <p className="max-w-prose text-sm leading-relaxed text-fg-2">{data?.note}</p>
        <Panel className="mt-3 px-4 py-2">
          <DataList>
            {(data?.data_collected ?? []).map((d: any, i: number) => (
              <DataRow key={i} label={d.item} value={d.sent_to_server ? d.leaves_to_ai : "nunca sai do computador"} note={d.sent_to_server ? undefined : "privado"} tone={d.sent_to_server ? undefined : "ok"} />
            ))}
          </DataList>
        </Panel>
      </Section>

      {data?.disclosures?.length > 0 && (
        <Section title="Exatamente o que a IA leu" description="Cada explicação enviada a um provedor, com o texto que ele recebeu">
          <div className="space-y-2">
            {data.disclosures.map((d: any, i: number) => (
              <details key={i} className="rounded-panel border border-hairline bg-surface px-4 py-2.5">
                <summary className="cursor-pointer text-sm text-fg-2">
                  {format(new Date(d.at), "dd/MM HH:mm", { locale: ptBR })} · {d.provider} ({d.destination === "cloud" ? "nuvem" : "local"})
                </summary>
                <pre className="mt-2 max-h-64 overflow-auto whitespace-pre-wrap rounded bg-sunken p-3 font-mono text-micro text-fg-3">{d.prompt_sent}</pre>
              </details>
            ))}
          </div>
        </Section>
      )}
    </div>
  );
}
