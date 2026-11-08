import { useEffect, useRef, useState } from "react";
import { Anomaly } from "../../types";
import { anomaliesApi } from "../../services/api";

/** Passos marcáveis; quando um não resolve, a IA gera o próximo, diferente dos que já falharam. */
export function AdaptiveSteps({ anomaly, onChange }: { anomaly: Anomaly; onChange: (a: Anomaly) => void }) {
  const steps = anomaly.explanation?.recommendations ?? [];
  const extra = anomaly.extra_steps ?? [];
  const [waitingNext, setWaitingNext] = useState(false);
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);
  useEffect(() => () => { if (pollRef.current) clearInterval(pollRef.current); }, []);

  const statusOf = (index: number, isExtra: boolean) =>
    (anomaly.steps_progress ?? []).find((p) => p.step_index === index && !!p.extra === isExtra)?.status;

  const mark = async (index: number, status: "done" | "not_helped", isExtra = false) => {
    const res = await anomaliesApi.step(anomaly.id, index, status, isExtra);
    onChange(res.data);
    if (status === "not_helped" && !isExtra) {
      // O backend gera o próximo passo em segundo plano; recarrega até aparecer
      setWaitingNext(true);
      const before = (res.data.extra_steps ?? []).length;
      pollRef.current = setInterval(async () => {
        const r = await anomaliesApi.get(anomaly.id);
        if ((r.data.extra_steps ?? []).length > before) {
          if (pollRef.current) clearInterval(pollRef.current);
          setWaitingNext(false);
          onChange(r.data);
        }
      }, 3000);
    }
  };

  if (steps.length === 0) return null;

  const StepRow = ({ text, index, isExtra, lastResort }: { text: string; index: number; isExtra?: boolean; lastResort?: boolean }) => {
    const status = statusOf(index, !!isExtra);
    const number = isExtra ? steps.length + index + 1 : index + 1;
    return (
      <li className="relative flex gap-4 pb-6 last:pb-0">
        <div className="relative flex w-6 flex-shrink-0 justify-center">
          <span
            className={`flex h-6 w-6 items-center justify-center rounded-full border ${
              status === "done" ? "border-ok bg-ok/10" : status === "not_helped" ? "border-edge bg-sunken" : "border-edge bg-surface"
            }`}
            aria-hidden="true"
          >
            <span className="tnum font-mono text-micro font-medium text-fg-2">{number}</span>
          </span>
          <span className="absolute bottom-0 top-7 w-px bg-hairline" aria-hidden="true" />
        </div>
        <div className="min-w-0 flex-1 pt-0.5">
          <p className={`max-w-prose text-sm leading-relaxed ${status === "done" ? "text-fg-3 line-through decoration-fg-3/40" : "text-fg-2"}`}>
            {lastResort && <span className="mr-1.5 font-medium text-warn">Último recurso:</span>}
            {text}
          </p>
          {status !== "done" && (
            <div className="mt-1.5 flex gap-3">
              <button type="button" onClick={() => mark(index, "done", isExtra)}
                className="rounded text-xs font-medium text-accent hover:underline">
                Fiz, resolveu
              </button>
              {!lastResort && (
                <button type="button" onClick={() => mark(index, "not_helped", isExtra)}
                  className="rounded text-xs text-fg-3 hover:text-fg-2 hover:underline">
                  Fiz, não resolveu
                </button>
              )}
            </div>
          )}
        </div>
      </li>
    );
  };

  return (
    <ol className="relative">
      {steps.map((step, i) => (
        <StepRow key={`s${i}`} text={step} index={i} />
      ))}
      {extra.map((step, i) => (
        <StepRow key={`e${i}`} text={step.text} index={i} isExtra lastResort={step.last_resort} />
      ))}
      {waitingNext && (
        <li className="flex gap-4 text-sm text-fg-3">
          <div className="flex w-6 justify-center">
            <span className="mt-1 h-4 w-4 animate-spin rounded-full border-2 border-edge border-t-fg-3" />
          </div>
          <span className="pt-0.5">Pensando no próximo passo…</span>
        </li>
      )}
    </ol>
  );
}
