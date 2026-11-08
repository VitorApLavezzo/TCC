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

/** A barra esvaziando mostra o tempo até a ação acontecer, sem exigir leitura. */
function Countdown({ run }: { run: Run }) {
  const [now, setNow] = useState(Date.now());

  useEffect(() => {
    const id = window.setInterval(() => setNow(Date.now()), 1000);
    return () => window.clearInterval(id);
  }, []);

  if (!run.undo_until || run.status !== "agendado") return null;
  const end = new Date(run.undo_until).getTime();
  const start = run.created_at ? new Date(run.created_at).getTime() : end - 120000;
  const total = Math.max(1, end - start);
  const remaining = Math.max(0, end - now);
  const seconds = Math.ceil(remaining / 1000);

  return (
    <div className="mt-2">
      <div className="h-1 overflow-hidden rounded-full bg-sunken" role="presentation">
        <div
          className="h-full rounded-full bg-warn transition-[width] duration-1000 ease-linear"
          style={{ width: `${(remaining / total) * 100}%` }}
        />
      </div>
      <p className="mt-1 tnum font-mono text-micro text-fg-3">
        {seconds > 0 ? `${seconds}s para cancelar` : "executando..."}
      </p>
    </div>
  );
}

/** O freio da automação: uma ação automática é anunciada e fica aqui enquanto dá para cancelar. */
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
    // A janela de cancelamento é curta: uma tela parada mostraria opção que já venceu.
    const id = window.setInterval(load, 15000);
    return () => window.clearInterval(id);
  }, [load]);

  if (runs.length === 0) return null;

  async function decide(run: Run, approve: boolean) {
    try {
      await playbooksApi.decide(run.id, approve);
      toast.success(approve ? "Ação liberada." : "Ação cancelada.");
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
              <Button size="sm" variant="primary" onClick={() => decide(run, true)}>
                Pode fazer
              </Button>
            )}
            <Button size="sm" variant="secondary" onClick={() => decide(run, false)}>
              Cancelar
            </Button>
          </div>
        </Panel>
      ))}
    </div>
  );
}
