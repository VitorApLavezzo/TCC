import { useEffect, useRef, useState } from "react";
import { actionsApi, errorMessage } from "../services/api";
import { DiagnosticResult } from "../types";
import { Button } from "./ui/Button";
import { useToast } from "./ui/Toast";
import { Gauge, X } from "lucide-react";

/** Pede ao agente 20 s de medição (uma por segundo) e a IA aponta o gargalo e o programa culpado. */
export function DiagnoseButton({
  machineId,
  online,
  variant = "secondary",
}: {
  machineId: number;
  online: boolean;
  variant?: "primary" | "secondary";
}) {
  const toast = useToast();
  const [result, setResult] = useState<DiagnosticResult | null>(null);
  const [running, setRunning] = useState(false);
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);
  useEffect(() => () => { if (pollRef.current) clearInterval(pollRef.current); }, []);

  const start = async () => {
    setRunning(true);
    setResult(null);
    try {
      const res = await actionsApi.diagnose(machineId);
      const id = res.data.diagnostic_id;
      let ticks = 0;
      pollRef.current = setInterval(async () => {
        ticks++;
        try {
          const r = await actionsApi.diagnostic(id);
          if (r.data.status === "done" || r.data.status === "failed") {
            if (pollRef.current) clearInterval(pollRef.current);
            setRunning(false);
            if (r.data.status === "done") setResult(r.data);
            else toast.error("Não foi possível concluir o diagnóstico.");
          } else if (ticks > 30) {
            if (pollRef.current) clearInterval(pollRef.current);
            setRunning(false);
            toast.error("O computador não respondeu a tempo.", "Ele pode estar offline ou muito sobrecarregado.");
          }
        } catch {
          /* continua */
        }
      }, 2000);
    } catch (err) {
      setRunning(false);
      toast.error(errorMessage(err));
    }
  };

  return (
    <div>
      <Button
        variant={variant}
        loading={running}
        loadingLabel="Medindo 20 segundos…"
        disabled={!online}
        title={online ? undefined : "O computador precisa estar enviando leituras"}
        icon={<Gauge size={14} aria-hidden="true" />}
        onClick={start}
      >
        Está lento agora, por quê?
      </Button>

      {result?.answer && (
        <div className="mt-4 rounded-panel border border-hairline bg-surface px-4 py-3.5">
          <div className="flex items-start justify-between gap-3">
            <p className="text-sm font-medium text-fg">{result.answer.headline}</p>
            <button type="button" onClick={() => setResult(null)} aria-label="Fechar" className="text-fg-3 hover:text-fg">
              <X size={14} aria-hidden="true" />
            </button>
          </div>
          <p className="mt-1.5 max-w-prose text-sm leading-relaxed text-fg-2">{result.answer.explanation}</p>
          {result.answer.actions?.length > 0 && (
            <ul className="mt-2.5 space-y-1">
              {result.answer.actions.map((a, i) => (
                <li key={i} className="flex gap-2 text-sm text-fg-2">
                  <span className="text-fg-3">→</span>
                  {a}
                </li>
              ))}
            </ul>
          )}
          {result.model_used && <p className="mt-2 text-micro text-fg-3">{result.model_used}</p>}
        </div>
      )}
    </div>
  );
}
