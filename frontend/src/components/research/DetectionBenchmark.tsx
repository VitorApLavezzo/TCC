import { useCallback, useEffect, useState } from "react";
import { evaluationApi, errorMessage } from "../../services/api";
import { Section, Panel } from "../ui/Layout";
import { Button, TextButton } from "../ui/Button";
import { Skeleton } from "../ui/Skeleton";
import { EmptyState } from "../ui/EmptyState";
import { useToast } from "../ui/Toast";
import { format } from "date-fns";
import { ptBR } from "date-fns/locale";

type Row = {
  name: string;
  label: string;
  family: string;
  expected: string | null;
  detected: string[];
  verdict: string;
};

const FAMILY_LABEL: Record<string, string> = {
  attack: "ataque",
  normal: "normal sintético",
  real: "normal real",
};

const pct = (v: number | null | undefined) => (v == null ? "—" : `${(v * 100).toFixed(1)}%`);

/**
 * Benchmark de detecção.
 *
 * A outra seção desta página mede a qualidade do texto que explica um
 * problema. Esta mede a função central — encontrar o problema e ficar calado
 * quando não há nenhum —, que é a afirmação que a banca vai querer ver com
 * número.
 *
 * A matriz vem primeiro porque é a resposta; a lista por cenário vem depois
 * porque é onde se responde "e nos casos em que erra?".
 */
export function DetectionBenchmark({ realMachineId }: { realMachineId?: number }) {
  const toast = useToast();
  const [data, setData] = useState<any>(null);
  const [loading, setLoading] = useState(true);
  const [running, setRunning] = useState(false);

  const load = useCallback(async () => {
    try {
      const r = await evaluationApi.benchmark();
      setData(r.data);
    } catch {
      setData(null);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  // Uma rodada leva minutos: em vez de travar a tela, busca o resultado de
  // tempos em tempos e para quando um mais novo aparece.
  useEffect(() => {
    if (!running) return;
    const inicial = data?.run?.id ?? null;
    const t = setInterval(async () => {
      const r = await evaluationApi.benchmark().catch(() => null);
      if (r && r.data?.run?.id && r.data.run.id !== inicial) {
        setData(r.data);
        setRunning(false);
        toast.success("Benchmark concluído.");
      }
    }, 5000);
    return () => clearInterval(t);
  }, [running, data?.run?.id, toast]);

  const run = async () => {
    setRunning(true);
    try {
      await evaluationApi.runBenchmark(realMachineId);
      toast.success("Benchmark iniciado — leva alguns minutos.");
    } catch (err) {
      setRunning(false);
      toast.error(errorMessage(err, "Não foi possível iniciar o benchmark."));
    }
  };

  const baixar = async (fmt: "md" | "csv") => {
    try {
      const r = await evaluationApi.benchmarkDownload(data.run.id, fmt);
      const blob = new Blob([r.data], { type: "text/plain;charset=utf-8" });
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = `benchmark-deteccao-${data.run.id}.${fmt}`;
      a.click();
      URL.revokeObjectURL(url);
    } catch (err) {
      toast.error(errorMessage(err, "Não foi possível baixar o relatório."));
    }
  };

  const m = data?.metrics;
  const rows: Row[] = data?.rows ?? [];

  return (
    <Section
      title="Benchmark de detecção"
      description="Cenários com gabarito passando pelo mesmo caminho da coleta real: acertos, escapadas e alarmes falsos"
      actions={
        <div className="flex flex-wrap items-center gap-3">
          {data?.run && (
            <>
              <TextButton onClick={() => baixar("md")}>Baixar .md</TextButton>
              <TextButton onClick={() => baixar("csv")}>Baixar .csv</TextButton>
            </>
          )}
          <Button size="sm" variant="secondary" onClick={run} loading={running} loadingLabel="Rodando...">
            Rodar benchmark
          </Button>
        </div>
      }
    >
      {loading ? (
        <Skeleton className="h-32 w-full rounded-panel" />
      ) : !data?.run ? (
        <EmptyState
          title="Nenhuma rodada ainda"
          body="O benchmark injeta cenários controlados de ataque e de uso normal e mede o que o sistema detectou. Leva alguns minutos."
          action={
            <Button variant="primary" onClick={run} loading={running} loadingLabel="Rodando...">
              Rodar agora
            </Button>
          }
        />
      ) : (
        <div className="space-y-5">
          <p className="text-xs text-fg-3">
            {format(new Date(data.run.created_at), "dd/MM/yyyy 'às' HH:mm", { locale: ptBR })} ·{" "}
            {m?.scenarios} cenários em {((data.run.duration_ms ?? 0) / 1000).toFixed(0)}s
          </p>

          <Panel>
            <div className="grid gap-x-8 gap-y-4 sm:grid-cols-4">
              <Metric label="Precisão" value={pct(m?.precision)} hint="dos avisos, quantos eram problema" />
              <Metric label="Revocação" value={pct(m?.recall)} hint="dos problemas, quantos foram achados" />
              <Metric label="F1" value={pct(m?.f1)} hint="equilíbrio entre as duas" />
              <Metric label="Alarme falso" value={pct(m?.false_positive_rate)} hint="do normal, quanto virou aviso" />
            </div>
          </Panel>

          <div className="overflow-x-auto">
            <table className="w-full min-w-[34rem] text-sm">
              <thead>
                <tr className="border-b border-hairline text-left">
                  <th className="channel-label pb-2 font-normal">Cenário</th>
                  <th className="channel-label pb-2 font-normal">Família</th>
                  <th className="channel-label pb-2 font-normal">Esperado</th>
                  <th className="channel-label pb-2 font-normal">Detectado</th>
                  <th className="channel-label pb-2 font-normal">Veredito</th>
                </tr>
              </thead>
              <tbody>
                {rows.map((r) => (
                  <tr key={r.name} className="border-b border-hairline/60">
                    <td className="py-2 pr-3 text-fg">{r.label}</td>
                    <td className="py-2 pr-3 text-fg-3">{FAMILY_LABEL[r.family] ?? r.family}</td>
                    <td className="py-2 pr-3 font-mono text-xs text-fg-2">{r.expected ?? "nenhum aviso"}</td>
                    <td className="py-2 pr-3 font-mono text-xs text-fg-2">
                      {r.detected?.length ? r.detected.join(", ") : "nada"}
                    </td>
                    <td className={`py-2 ${r.verdict === "acerto" ? "text-ok" : "text-warn"}`}>{r.verdict}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </Section>
  );
}

function Metric({ label, value, hint }: { label: string; value: string; hint: string }) {
  return (
    <div className="min-w-0">
      <p className="channel-label">{label}</p>
      <p className="tnum mt-0.5 font-mono text-readout-sm font-medium text-fg">{value}</p>
      <p className="mt-0.5 text-micro leading-snug text-fg-3">{hint}</p>
    </div>
  );
}
