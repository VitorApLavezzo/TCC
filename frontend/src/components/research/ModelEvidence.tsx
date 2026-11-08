import { useCallback, useEffect, useState } from "react";
import { decimal } from "../../lib/format";
import { Line, LineChart, ResponsiveContainer, XAxis, YAxis } from "recharts";
import { errorMessage, evaluationApi, machinesApi } from "../../services/api";
import { Section, Panel } from "../ui/Layout";
import { Button } from "../ui/Button";
import { EmptyState } from "../ui/EmptyState";
import { useToast } from "../ui/Toast";

type AblationRow = {
  layer: string;
  label: string;
  precision: number | null;
  recall: number | null;
  f1: number | null;
  true_positives: number;
  /** Ataques com algum aviso, mesmo de outro tipo. */
  seen?: number | null;
  false_positives: number;
};

const pct = (v: number | null | undefined) => (v == null ? "—" : `${decimal(v * 100, 1)}%`);

// O modelo acrescenta algo às regras (ablação)? Separa melhor que um limiar fixo de três desvios (holdout temporal, AUC)?
const SENSITIVITY_DETECTORS = [
  { id: "isolation_forest", name: "Isolation Forest" },
  { id: "one_class_svm", name: "One-Class SVM" },
  { id: "sigma_baseline", name: "Limiar de 3 desvios" },
] as const;

export function ModelEvidence() {
  const toast = useToast();
  const [ablation, setAblation] = useState<any>(null);
  const [running, setRunning] = useState(false);
  const [machines, setMachines] = useState<{ id: number; name: string }[]>([]);
  const [machineId, setMachineId] = useState<string>("");
  const [holdout, setHoldout] = useState<any>(null);
  const [loadingHoldout, setLoadingHoldout] = useState(false);

  const loadAblation = useCallback(async () => {
    try {
      const r = await evaluationApi.ablation();
      setAblation(r.data);
      return r.data?.status;
    } catch {
      return "none";
    }
  }, []);

  useEffect(() => {
    loadAblation();
    machinesApi
      .list()
      .then((r) => setMachines(r.data.map((m: any) => ({ id: m.id, name: m.name }))))
      .catch(() => setMachines([]));
  }, [loadAblation]);

  async function runAblation() {
    setRunning(true);
    try {
      await evaluationApi.runAblation();
      toast.info("Rodando os cenários três vezes.", "Leva alguns minutos; o resultado aparece aqui.");
      // Os cenários passam pelo pipeline real: lento demais para uma requisição, então consulta periodicamente.
      const timer = window.setInterval(async () => {
        const status = await loadAblation();
        if (status !== "running") {
          window.clearInterval(timer);
          setRunning(false);
        }
      }, 5000);
    } catch (e) {
      toast.error(errorMessage(e));
      setRunning(false);
    }
  }

  async function loadHoldout(id: string) {
    setMachineId(id);
    if (!id) return setHoldout(null);
    setLoadingHoldout(true);
    try {
      const r = await evaluationApi.holdout(Number(id));
      setHoldout(r.data);
    } catch (e) {
      toast.error(errorMessage(e));
    } finally {
      setLoadingHoldout(false);
    }
  }

  const rows: AblationRow[] = ablation?.rows ?? [];
  // Cada curva ROC com os próprios pares (fpr, tpr): emparelhar pelo índice desenharia nas posições x erradas.
  const curves = [
    { id: "isolation", name: "Isolation Forest", points: holdout?.roc ?? [],
      colorClass: "text-series-1", width: 2, dash: undefined },
    { id: "svm", name: "One-Class SVM", points: holdout?.roc_ocsvm ?? [],
      colorClass: "text-series-2", width: 2, dash: "6 3" },
    { id: "limiar", name: "Limiar de 3 desvios", points: holdout?.roc_baseline ?? [],
      colorClass: "text-fg-3", width: 1.5, dash: "2 3" },
  ].filter((c) => c.points.length > 0);

  return (
    <div className="space-y-8">
      <Section
        title="O que cada camada detecta"
        description="Os mesmos cenários rodados três vezes: só regras, só modelo, os dois juntos"
        actions={
          <Button size="sm" variant="secondary" loading={running || ablation?.status === "running"} onClick={runAblation}>
            Rodar ablação
          </Button>
        }
      >
        {rows.length === 0 ? (
          <EmptyState
            title="Ablação ainda não rodada"
            body="É a resposta em número para “o modelo acrescenta alguma coisa às regras?”."
          />
        ) : (
          <>
            <div className="scroll-hint overflow-x-auto">
              <table className="w-full text-sm">
                <thead>
                  <tr className="border-b border-hairline text-left text-micro uppercase tracking-wide text-fg-3">
                    <th className="py-2 font-medium">Camada</th>
                    <th className="py-2 text-right font-medium">Precisão</th>
                    <th className="py-2 text-right font-medium">Revocação</th>
                    <th className="py-2 text-right font-medium">F1</th>
                    <th className="py-2 text-right font-medium">Acertos</th>
                    <th className="py-2 text-right font-medium" title="Ataques com algum aviso, mesmo com outro nome">
                      Viu
                    </th>
                    <th className="py-2 text-right font-medium">Falsos positivos</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-hairline">
                  {rows.map((l) => (
                    <tr key={l.layer}>
                      <td className="py-2 text-fg-2">{l.label}</td>
                      <td className="tnum py-2 text-right font-mono text-fg">{pct(l.precision)}</td>
                      <td className="tnum py-2 text-right font-mono text-fg">{pct(l.recall)}</td>
                      <td className="tnum py-2 text-right font-mono text-fg">{pct(l.f1)}</td>
                      <td className="tnum py-2 text-right font-mono text-fg-2">{l.true_positives}</td>
                      <td className="tnum py-2 text-right font-mono text-fg-2">{l.seen ?? "—"}</td>
                      <td className="tnum py-2 text-right font-mono text-fg-2">{l.false_positives}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            {ablation?.sentence && (
              <p className="mt-3 max-w-prose text-sm leading-relaxed text-fg-2">{ablation.sentence}</p>
            )}
          </>
        )}
      </Section>

      <Section
        title="Isolation Forest contra as alternativas"
        description="Treino na primeira parte do histórico, medição na parte final que ele nunca viu"
        actions={
          <select
            aria-label="Computador usado na validação"
            value={machineId}
            onChange={(e) => loadHoldout(e.target.value)}
            className="h-8 rounded-control border border-edge bg-surface px-2 text-sm text-fg focus:border-accent"
          >
            <option value="">Escolha um computador</option>
            {machines.map((m) => (
              <option key={m.id} value={m.id}>
                {m.name}
              </option>
            ))}
          </select>
        }
      >
        {!holdout ? (
          <EmptyState
            title={loadingHoldout ? "Calculando..." : "Escolha um computador"}
            body="A validação usa o histórico real da máquina, com anomalias injetadas nas leituras de teste."
          />
        ) : !holdout.ready ? (
          <p className="text-sm text-fg-2">{holdout.reason}</p>
        ) : (
          <div className="grid gap-4 lg:grid-cols-2">
            <Panel className="p-4">
              <p className="channel-label">Anomalia em várias medidas ao mesmo tempo</p>
              <dl className="mt-2 space-y-2 text-sm">
                <div className="flex justify-between gap-4">
                  <dt className="text-fg-2">Área sob a curva — Isolation Forest</dt>
                  <dd className="tnum font-mono text-fg">{decimal(holdout.auc_model, 3)}</dd>
                </div>
                {holdout.auc_ocsvm != null && (
                  <div className="flex justify-between gap-4">
                    <dt className="text-fg-2">Área sob a curva — One-Class SVM</dt>
                    <dd className="tnum font-mono text-fg">{decimal(holdout.auc_ocsvm, 3)}</dd>
                  </div>
                )}
                <div className="flex justify-between gap-4">
                  <dt className="text-fg-2">Área sob a curva — limiar de 3 desvios</dt>
                  <dd className="tnum font-mono text-fg">{decimal(holdout.auc_sigma_baseline, 3)}</dd>
                </div>
                <div className="flex justify-between gap-4 border-t border-hairline pt-2">
                  <dt className="text-fg-2">Precisão no limiar em uso</dt>
                  <dd className="tnum font-mono text-fg">{pct(holdout.operating_point.precision)}</dd>
                </div>
                <div className="flex justify-between gap-4">
                  <dt className="text-fg-2">Revocação no limiar em uso</dt>
                  <dd className="tnum font-mono text-fg">{pct(holdout.operating_point.recall)}</dd>
                </div>
                <div className="flex justify-between gap-4">
                  <dt className="text-fg-2">Treino / teste / injetadas</dt>
                  <dd className="tnum font-mono text-fg-2">
                    {holdout.samples_train} / {holdout.samples_test} / {holdout.samples_injected}
                  </dd>
                </div>
              </dl>
              <p className="mt-3 max-w-prose text-sm leading-relaxed text-fg-2">{holdout.verdict}</p>
            </Panel>

            <Panel className="p-4">
              <p className="channel-label">Curva ROC</p>
              <ul className="mt-2 flex flex-wrap gap-x-4 gap-y-1 text-micro text-fg-2" aria-label="Legenda">
                {curves.map((c) => (
                  <li key={c.id} className="inline-flex items-center gap-1.5">
                    <svg width="20" height="6" aria-hidden="true" className={c.colorClass}>
                      <line x1="0" y1="3" x2="20" y2="3" stroke="currentColor" strokeWidth={c.width}
                            strokeDasharray={c.dash} />
                    </svg>
                    {c.name}
                  </li>
                ))}
              </ul>
              <div className="mt-2 h-48">
                <ResponsiveContainer width="100%" height="100%">
                  <LineChart margin={{ top: 4, right: 8, bottom: 4, left: -20 }}>
                    <XAxis dataKey="fpr" type="number" domain={[0, 1]} tick={{ fontSize: 10 }} />
                    <YAxis type="number" domain={[0, 1]} tick={{ fontSize: 10 }} />
                    {curves.map((c) => (
                      <Line key={c.id} data={c.points} dataKey="tpr" name={c.name} type="linear"
                            dot={false} isAnimationActive={false} strokeWidth={c.width}
                            strokeDasharray={c.dash} stroke="currentColor" className={c.colorClass} />
                    ))}
                  </LineChart>
                </ResponsiveContainer>
              </div>
              <p className="mt-1 text-micro text-fg-3">
                Quanto mais para o canto superior esquerdo, melhor.
              </p>
            </Panel>

            {holdout.sensitivity && (
              <Panel className="p-4 lg:col-span-2">
                <p className="channel-label">Anomalia em uma medida só</p>
                <p className="mt-1 max-w-prose text-sm leading-relaxed text-fg-2">
                  Uma única medida deslocada para cima, em desvios-padrão do treino. É onde os
                  detectores se diferenciam: com várias medidas mexendo juntas, todos acertam.
                </p>
                <div className="scroll-hint mt-3 overflow-x-auto">
                  <table className="w-full text-sm">
                    <caption className="sr-only">
                      Área sob a curva de cada detector por intensidade do desvio. O maior valor de
                      cada linha está em negrito.
                    </caption>
                    <thead>
                      <tr className="border-b border-hairline text-left text-micro uppercase tracking-wide text-fg-3">
                        <th className="py-2 font-medium">Desvio</th>
                        {SENSITIVITY_DETECTORS.map((d) => (
                          <th key={d.id} className="py-2 text-right font-medium">{d.name}</th>
                        ))}
                      </tr>
                    </thead>
                    <tbody className="divide-y divide-hairline">
                      {holdout.sensitivity.rows.map((l: any) => {
                        const best = Math.max(...SENSITIVITY_DETECTORS.map((d) => l[d.id]));
                        return (
                          <tr key={l.sigma}>
                            <td className="py-2 text-fg-2">
                              {l.sigma} {l.sigma === 1 ? "desvio-padrão" : "desvios-padrão"}
                            </td>
                            {SENSITIVITY_DETECTORS.map((d) => (
                              <td key={d.id}
                                  className={`tnum py-2 text-right font-mono ${
                                    l[d.id] === best ? "font-semibold text-fg" : "text-fg-2"
                                  }`}>
                                {decimal(l[d.id], 3)}
                              </td>
                            ))}
                          </tr>
                        );
                      })}
                    </tbody>
                  </table>
                </div>
                {holdout.sensitivity_verdict && (
                  <p className="mt-3 max-w-prose text-sm leading-relaxed text-fg-2">{holdout.sensitivity_verdict}</p>
                )}
                {holdout.algorithm_verdict && (
                  <p className="mt-2 max-w-prose text-sm leading-relaxed text-fg-2">{holdout.algorithm_verdict}</p>
                )}
              </Panel>
            )}
          </div>
        )}
      </Section>
    </div>
  );
}
