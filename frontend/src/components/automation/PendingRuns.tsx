import { useCallback, useEffect, useState } from "react";
import { errorMessage, playbooksApi } from "../../services/api";
import { Panel } from "../ui/Layout";
import { Button } from "../ui/Button";
import { useToast } from "../ui/Toast";

type Run = {
  id: number;
  status: string;
  status_label: string;
  detail: string | null;
  undo_until: string | null;
  created_at: string | null;
  can_cancel: boolean;
  can_approve: boolean;
};

/**
 * O tempo que resta antes da ação acontecer, visível.
 *
 * O texto dizia "executa em 2 min" e pedia confiança. A barra esvaziando
 * mostra o tempo correndo: é o mesmo dado, num canal que não exige leitura —
 * e é o que torna a automação aceitável para quem não é técnico.
 */
function Countdown({ run }: { run: Run }) {
  const [agora, setAgora] = useState(Date.now());

  useEffect(() => {
    const id = window.setInterval(() => setAgora(Date.now()), 1000);
    return () => window.clearInterval(id);
  }, []);

  if (!run.undo_until || run.status !== "agendado") return null;
  const fim = new Date(run.undo_until).getTime();
  const inicio = run.created_at ? new Date(run.created_at).getTime() : fim - 120000;
  const total = Math.max(1, fim - inicio);
  const restante = Math.max(0, fim - agora);
  const segundos = Math.ceil(restante / 1000);

  return (
    <div className="mt-2">
      <div className="h-1 overflow-hidden rounded-full bg-sunken" role="presentation">
        <div
          className="h-full rounded-full bg-warn transition-[width] duration-1000 ease-linear"
          style={{ width: `${(restante / total) * 100}%` }}
        />
      </div>
      <p className="mt-1 tnum font-mono text-micro text-fg-3">
        {segundos > 0 ? `${segundos}s para cancelar` : "executando..."}
      </p>
    </div>
  );
}

/**
 * O freio da automação.
 *
 * Uma ação automática é anunciada antes de acontecer e fica aqui, com o
 * relógio correndo, enquanto dá para cancelar. É o que separa "o sistema
 * age sozinho" de "o sistema age pelas suas costas": a diferença é só esta
 * janela, mas é ela que torna a automação aceitável para quem não é técnico.
 */
export function PendingRuns() {
  const toast = useToast();
  const [runs, setRuns] = useState<Run[]>([]);

  const load = useCallback(async () => {
    try {
      const r = await playbooksApi.runs({ limit: 10 });
      setRuns((r.data.runs as Run[]).filter((x) => x.can_cancel));
    } catch {
      setRuns([]);
    }
  }, []);

  useEffect(() => {
    load();
    // Enquanto há algo a decidir, a lista se atualiza sozinha: a janela de
    // cancelamento é curta e uma tela parada mostraria opção que já venceu.
    const id = window.setInterval(load, 15000);
    return () => window.clearInterval(id);
  }, [load]);

  if (runs.length === 0) return null;

  async function decidir(run: Run, aprovar: boolean) {
    try {
      await playbooksApi.decide(run.id, aprovar);
      toast.success(aprovar ? "Ação liberada." : "Ação cancelada.");
      load();
    } catch (e) {
      toast.error(errorMessage(e));
    }
  }

  return (
    <div className="space-y-2">
      {runs.map((run) => (
        <Panel key={run.id} className="flex flex-wrap items-center justify-between gap-3 p-3">
          <div className="min-w-0">
            <p className="text-sm font-semibold text-fg">{run.status_label}</p>
            <p className="mt-0.5 text-xs text-fg-2">{run.detail}</p>
            <Countdown run={run} />
          </div>
          <div className="flex flex-shrink-0 gap-2">
            {run.can_approve && (
              <Button size="sm" variant="primary" onClick={() => decidir(run, true)}>
                Pode fazer
              </Button>
            )}
            <Button size="sm" variant="secondary" onClick={() => decidir(run, false)}>
              Cancelar
            </Button>
          </div>
        </Panel>
      ))}
    </div>
  );
}
