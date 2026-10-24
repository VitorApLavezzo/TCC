import { useCallback, useEffect, useRef, useState } from "react";
import { decimal } from "../../lib/format";
import { errorMessage, evaluationApi, machinesApi } from "../../services/api";
import { Section, Panel, DataList, DataRow } from "../ui/Layout";
import { Button } from "../ui/Button";
import { EmptyState } from "../ui/EmptyState";
import { Skeleton } from "../ui/Skeleton";
import { useToast } from "../ui/Toast";

type Confusion = {
  true_positives: number;
  false_negatives: number;
  false_positives: number;
  true_negatives: number;
  false_positives_generated: number;
  precision: number | null;
  recall: number | null;
  interrupted_tests: number;
};

type Benign = {
  sessions: number;
  hours: number;
  interruptions: number;
  interruptions_per_hour: number | null;
  sessions_with_interruption: number;
  generated: number;
};

type TestRow = {
  name: string;
  sessions: number;
  detected: number;
  interrupted: number;
  median_seconds_to_detection: number | null;
};

type Score = { confusion: Confusion; benign: Benign; tests: Record<string, TestRow> };

const pct = (v: number | null | undefined) => (v == null ? "—" : `${decimal(v * 100, 1)}%`);
const num = (v: number, casas = 1) => v.toLocaleString("pt-BR", { maximumFractionDigits: casas });
const tempo = (s: number | null) => (s == null ? "—" : s < 120 ? `${Math.round(s)} s` : `${num(s / 60)} min`);

/**
 * O resultado do TCC: o que o sistema fez nas sessões que a pessoa marcou.
 *
 * Sessão de uso legítimo (jogo, trabalho pesado, uso normal) com aviso que
 * interrompeu é alarme falso; teste atômico (minerador, disfarce, isca,
 * contato periódico) só conta com a evidência certa. A reprodução passa as
 * mesmas leituras de novo com e sem contexto de uso e camada por camada.
 */
export function RealEvaluation() {
  const toast = useToast();
  const [machines, setMachines] = useState<{ id: number; name: string }[]>([]);
  const [machineId, setMachineId] = useState<string>("");
  const [days, setDays] = useState(14);
  const [data, setData] = useState<{ live: Score & { sessions: unknown[] }; replay: any } | null>(null);
  const [loading, setLoading] = useState(false);
  const timer = useRef<number | null>(null);

  useEffect(() => {
    machinesApi
      .list()
      .then((r) => setMachines(r.data.map((m: any) => ({ id: m.id, name: m.name }))))
      .catch(() => setMachines([]));
    return () => {
      if (timer.current) window.clearInterval(timer.current);
    };
  }, []);

  const load = useCallback(async () => {
    if (!machineId) return null;
    try {
      const r = await evaluationApi.real(Number(machineId), days);
      setData(r.data);
      return r.data?.replay?.status as string;
    } catch (e) {
      toast.error(errorMessage(e));
      return "error";
    }
  }, [machineId, days, toast]);

  useEffect(() => {
    if (!machineId) return setData(null);
    setLoading(true);
    load().finally(() => setLoading(false));
  }, [machineId, days, load]);

  async function reproduzir() {
    try {
      await evaluationApi.runRealReplay(Number(machineId), days);
      toast.info("Reproduzindo as sessões quatro vezes.", "Pode levar dezenas de minutos; o resultado aparece aqui.");
      setData((d) => (d ? { ...d, replay: { status: "running" } } : d));
      if (timer.current) window.clearInterval(timer.current);
      timer.current = window.setInterval(async () => {
        const status = await load();
        if (status !== "running" && timer.current) {
          window.clearInterval(timer.current);
          timer.current = null;
        }
      }, 10000);
    } catch (e) {
      toast.error(errorMessage(e));
    }
  }

  const live = data?.live;
  const semSessoes = live && live.sessions.length === 0;
  const testes = Object.entries(live?.tests ?? {});
  const replay = data?.replay;
  const configs = Object.entries((replay?.configs ?? {}) as Record<string, Score & { label: string }>);

  return (
    <Section
      title="Resultado em dado real"
      description="As sessões que você marcou no computador cruzadas com os avisos que o sistema deu de verdade"
      actions={
        <div className="flex flex-wrap items-center gap-2">
          <select
            value={machineId}
            onChange={(e) => setMachineId(e.target.value)}
            aria-label="Computador avaliado"
            className="h-8 rounded-control border border-edge bg-surface px-2 text-sm text-fg focus:border-accent"
          >
            <option value="">Escolha o computador</option>
            {machines.map((m) => (
              <option key={m.id} value={m.id}>
                {m.name}
              </option>
            ))}
          </select>
          <select
            value={days}
            onChange={(e) => setDays(Number(e.target.value))}
            aria-label="Período avaliado"
            className="h-8 rounded-control border border-edge bg-surface px-2 text-sm text-fg focus:border-accent"
          >
            <option value={7}>7 dias</option>
            <option value={14}>14 dias</option>
            <option value={30}>30 dias</option>
            <option value={90}>90 dias</option>
          </select>
        </div>
      }
    >
      {!machineId ? (
        <EmptyState
          title="Escolha um computador"
          body="O resultado sai das sessões marcadas em “O que estou fazendo”, na bandeja do agente ou na página do computador."
        />
      ) : loading && !data ? (
        <Skeleton className="h-40 w-full rounded-panel" />
      ) : semSessoes ? (
        <EmptyState
          title="Nenhuma sessão marcada neste período"
          body="Marque o que está fazendo (jogando, trabalho pesado, uso normal ou um teste) pela bandeja do agente ou pela página do computador. Cada sessão marcada vira uma linha desta avaliação."
        />
      ) : live ? (
        <div className="space-y-6">
          <div className="grid gap-4 md:grid-cols-2">
            <Panel className="p-4">
              <p className="mb-2 text-sm font-medium text-fg">Uso legítimo</p>
              <DataList>
                <DataRow label="Sessões" value={`${live.benign.sessions} (${num(live.benign.hours)} h)`} />
                <DataRow
                  label="Avisos que interromperam"
                  value={live.benign.interruptions}
                  tone={live.benign.interruptions ? "warn" : "ok"}
                />
                <DataRow
                  label="Por hora"
                  value={live.benign.interruptions_per_hour == null ? "—" : num(live.benign.interruptions_per_hour, 2)}
                />
                <DataRow label="Sessões com alguma interrupção" value={live.benign.sessions_with_interruption} />
                <DataRow label="Avisos registrados (qualquer gravidade)" value={live.benign.generated} />
              </DataList>
            </Panel>
            <Panel className="p-4">
              <p className="mb-2 text-sm font-medium text-fg">Por sessão</p>
              <DataList>
                <DataRow label="Testes detectados" value={`${live.confusion.true_positives} de ${live.confusion.true_positives + live.confusion.false_negatives}`} />
                <DataRow label="Testes que interromperam" value={live.confusion.interrupted_tests} />
                <DataRow label="Alarmes falsos (interromperam)" value={live.confusion.false_positives} />
                <DataRow label="Precisão" value={pct(live.confusion.precision)} mono />
                <DataRow label="Revocação" value={pct(live.confusion.recall)} mono />
              </DataList>
            </Panel>
          </div>

          {testes.length > 0 && (
            <div className="scroll-hint overflow-x-auto">
              <table className="w-full text-sm">
                <thead>
                  <tr className="border-b border-hairline text-left text-micro uppercase tracking-wide text-fg-3">
                    <th className="py-2 font-medium">Teste</th>
                    <th className="py-2 text-right font-medium">Sessões</th>
                    <th className="py-2 text-right font-medium">Detectado</th>
                    <th className="py-2 text-right font-medium">Interrompeu</th>
                    <th className="py-2 text-right font-medium">Tempo até detectar</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-hairline">
                  {testes.map(([id, t]) => (
                    <tr key={id}>
                      <td className="py-2 text-fg-2">{t.name}</td>
                      <td className="tnum py-2 text-right font-mono text-fg-2">{t.sessions}</td>
                      <td className="tnum py-2 text-right font-mono text-fg">{t.detected}</td>
                      <td className="tnum py-2 text-right font-mono text-fg">{t.interrupted}</td>
                      <td className="tnum py-2 text-right font-mono text-fg-2">{tempo(t.median_seconds_to_detection)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}

          <div>
            <div className="mb-3 flex flex-wrap items-center justify-between gap-3">
              <p className="max-w-prose text-sm text-fg-2">
                Reprodução: as mesmas leituras passam de novo pelo sistema, com e sem contexto de uso e camada por
                camada.
              </p>
              <Button size="sm" variant="secondary" loading={replay?.status === "running"} onClick={reproduzir}>
                Reproduzir
              </Button>
            </div>
            {replay?.status === "error" && <p className="text-sm text-crit">A reprodução falhou: {replay.detail}</p>}
            {configs.length > 0 && (
              <>
                <div className="scroll-hint overflow-x-auto">
                  <table className="w-full text-sm">
                    <thead>
                      <tr className="border-b border-hairline text-left text-micro uppercase tracking-wide text-fg-3">
                        <th className="py-2 font-medium">Configuração</th>
                        <th className="py-2 text-right font-medium">Interrupções no uso legítimo</th>
                        <th className="py-2 text-right font-medium">Testes detectados</th>
                        <th className="py-2 text-right font-medium">Precisão</th>
                        <th className="py-2 text-right font-medium">Revocação</th>
                      </tr>
                    </thead>
                    <tbody className="divide-y divide-hairline">
                      {configs.map(([id, c]) => (
                        <tr key={id}>
                          <td className="py-2 text-fg-2">{c.label}</td>
                          <td className="tnum py-2 text-right font-mono text-fg">{c.benign.interruptions}</td>
                          <td className="tnum py-2 text-right font-mono text-fg">
                            {c.confusion.true_positives} de {c.confusion.true_positives + c.confusion.false_negatives}
                          </td>
                          <td className="tnum py-2 text-right font-mono text-fg-2">{pct(c.confusion.precision)}</td>
                          <td className="tnum py-2 text-right font-mono text-fg-2">{pct(c.confusion.recall)}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
                {replay?.sentence && (
                  <p className="mt-3 max-w-prose text-sm leading-relaxed text-fg-2">{replay.sentence}</p>
                )}
              </>
            )}
          </div>
        </div>
      ) : null}
    </Section>
  );
}
