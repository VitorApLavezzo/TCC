import { useCallback, useEffect, useState } from "react";
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
  false_positives: number;
};

const pct = (v: number | null | undefined) => (v == null ? "—" : `${(v * 100).toFixed(1)}%`);

/**
 * A evidência sobre a parte de aprendizado de máquina.
 *
 * Duas perguntas que uma banca faz e que o benchmark geral não responde: o
 * modelo acrescenta algo às regras (ablação), e ele separa melhor que um
 * limiar fixo de três desvios (retenção temporal, com área sob a curva).
 */
export function ModelEvidence() {
  const toast = useToast();
  const [ablation, setAblation] = useState<any>(null);
  const [rodando, setRodando] = useState(false);
  const [machines, setMachines] = useState<{ id: number; name: string }[]>([]);
  const [machineId, setMachineId] = useState<string>("");
  const [holdout, setHoldout] = useState<any>(null);
  const [carregandoHoldout, setCarregandoHoldout] = useState(false);

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

  async function rodarAblacao() {
    setRodando(true);
    try {
      await evaluationApi.runAblation();
      toast.info("Rodando os cenários três vezes.", "Leva alguns minutos; o resultado aparece aqui.");
      // Os cenários passam pelo pipeline real: é lento e não cabe numa
      // requisição. A tela busca o resultado de tempos em tempos.
      const timer = window.setInterval(async () => {
        const status = await loadAblation();
        if (status !== "running") {
          window.clearInterval(timer);
          setRodando(false);
        }
      }, 5000);
    } catch (e) {
      toast.error(errorMessage(e));
      setRodando(false);
    }
  }

  async function rodarHoldout(id: string) {
    setMachineId(id);
    if (!id) return setHoldout(null);
    setCarregandoHoldout(true);
    try {
      const r = await evaluationApi.holdout(Number(id));
      setHoldout(r.data);
    } catch (e) {
      toast.error(errorMessage(e));
    } finally {
      setCarregandoHoldout(false);
    }
  }

  const linhas: AblationRow[] = ablation?.rows ?? [];
  const curva = (holdout?.roc ?? []).map((p: any, i: number) => ({
    fpr: p.fpr,
    modelo: p.tpr,
    limiar: holdout?.roc_baseline?.[i]?.tpr ?? null,
  }));

  return (
    <div className="space-y-8">
      <Section
        title="O que cada camada detecta"
        description="Os mesmos cenários rodados três vezes: só regras, só modelo, os dois juntos"
        actions={
          <Button size="sm" variant="secondary" loading={rodando || ablation?.status === "running"} onClick={rodarAblacao}>
            Rodar ablação
          </Button>
        }
      >
        {linhas.length === 0 ? (
          <EmptyState
            title="Ablação ainda não rodada"
            body="É a resposta em número para “o modelo acrescenta alguma coisa às regras?”."
          />
        ) : (
          <>
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead>
                  <tr className="border-b border-hairline text-left text-micro uppercase tracking-wide text-fg-3">
                    <th className="py-2 font-medium">Camada</th>
                    <th className="py-2 text-right font-medium">Precisão</th>
                    <th className="py-2 text-right font-medium">Revocação</th>
                    <th className="py-2 text-right font-medium">F1</th>
                    <th className="py-2 text-right font-medium">Acertos</th>
                    <th className="py-2 text-right font-medium">Falsos positivos</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-hairline">
                  {linhas.map((l) => (
                    <tr key={l.layer}>
                      <td className="py-2 text-fg-2">{l.label}</td>
                      <td className="tnum py-2 text-right font-mono text-fg">{pct(l.precision)}</td>
                      <td className="tnum py-2 text-right font-mono text-fg">{pct(l.recall)}</td>
                      <td className="tnum py-2 text-right font-mono text-fg">{pct(l.f1)}</td>
                      <td className="tnum py-2 text-right font-mono text-fg-2">{l.true_positives}</td>
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
        title="O modelo contra um limiar fixo"
        description="Treino na primeira parte do histórico, medição na parte final que ele nunca viu"
        actions={
          <select
            value={machineId}
            onChange={(e) => rodarHoldout(e.target.value)}
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
            title={carregandoHoldout ? "Calculando..." : "Escolha um computador"}
            body="A validação usa o histórico real da máquina, com anomalias injetadas nas leituras de teste."
          />
        ) : !holdout.ready ? (
          <p className="text-sm text-fg-2">{holdout.reason}</p>
        ) : (
          <div className="grid gap-4 lg:grid-cols-2">
            <Panel className="p-4">
              <dl className="space-y-2 text-sm">
                <div className="flex justify-between gap-4">
                  <dt className="text-fg-2">Área sob a curva — modelo</dt>
                  <dd className="tnum font-mono text-fg">{holdout.auc_model.toFixed(3)}</dd>
                </div>
                <div className="flex justify-between gap-4">
                  <dt className="text-fg-2">Área sob a curva — limiar de 3 desvios</dt>
                  <dd className="tnum font-mono text-fg">{holdout.auc_sigma_baseline.toFixed(3)}</dd>
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
              <div className="mt-2 h-48">
                <ResponsiveContainer width="100%" height="100%">
                  <LineChart data={curva} margin={{ top: 4, right: 8, bottom: 4, left: -20 }}>
                    <XAxis dataKey="fpr" type="number" domain={[0, 1]} tick={{ fontSize: 10 }} />
                    <YAxis type="number" domain={[0, 1]} tick={{ fontSize: 10 }} />
                    <Line type="monotone" dataKey="modelo" dot={false} strokeWidth={2} stroke="currentColor"
                          className="text-accent" />
                    <Line type="monotone" dataKey="limiar" dot={false} strokeWidth={1.5} strokeDasharray="4 3"
                          stroke="currentColor" className="text-fg-3" />
                  </LineChart>
                </ResponsiveContainer>
              </div>
              <p className="mt-1 text-micro text-fg-3">
                Linha cheia: modelo. Tracejada: limiar fixo. Quanto mais para o canto superior
                esquerdo, melhor.
              </p>
            </Panel>
          </div>
        )}
      </Section>
    </div>
  );
}
