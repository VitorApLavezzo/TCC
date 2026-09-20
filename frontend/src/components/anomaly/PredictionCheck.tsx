import { useEffect, useState } from "react";
import { evaluationApi } from "../../services/api";
import { Panel, StatusDot } from "../ui/Layout";

type Outcome = {
  status: "pending" | "measured" | "expired" | "none";
  sentence?: string;
  hit?: boolean | null;
  metric_label?: string;
  baseline_value?: number;
  predicted_value?: number;
  observed_value?: number;
  error?: number | null;
  model_used?: string | null;
};

/**
 * Conferência da previsão.
 *
 * O cartão "e se eu fechar?" promete um número. Depois da ação, este bloco
 * diz se o número se confirmou. É o fechamento do laço: a IA não só explica,
 * ela fica registrada errando ou acertando — e a taxa aparece na página de
 * pesquisa, por provedor.
 */
export function PredictionCheck({ anomalyId }: { anomalyId: number }) {
  const [outcome, setOutcome] = useState<Outcome | null>(null);

  useEffect(() => {
    let vivo = true;
    evaluationApi
      .fidelityForAnomaly(anomalyId)
      .then((r) => vivo && setOutcome(r.data))
      .catch(() => vivo && setOutcome(null));
    return () => {
      vivo = false;
    };
  }, [anomalyId]);

  // Sem ação executada ainda não há previsão para conferir — e um bloco
  // dizendo isso só ocuparia a tela.
  if (!outcome || outcome.status === "none") return null;

  const tone = outcome.status === "pending" ? "idle" : outcome.hit ? "ok" : "warn";

  return (
    <Panel className="p-4">
      <p className="channel-label">Conferência da previsão</p>
      <p className="mt-2 flex items-start gap-2 text-sm leading-relaxed text-fg-2">
        <StatusDot tone={tone} className="mt-1.5" />
        <span>{outcome.sentence}</span>
      </p>
      {outcome.status === "measured" && (
        <dl className="mt-3 flex flex-wrap gap-x-6 gap-y-1 border-t border-hairline pt-3 text-micro">
          <div className="flex gap-1.5">
            <dt className="text-fg-3">antes</dt>
            <dd className="tnum font-mono text-fg-2">{outcome.baseline_value?.toFixed(0)}%</dd>
          </div>
          <div className="flex gap-1.5">
            <dt className="text-fg-3">previsto</dt>
            <dd className="tnum font-mono text-fg-2">{outcome.predicted_value?.toFixed(0)}%</dd>
          </div>
          <div className="flex gap-1.5">
            <dt className="text-fg-3">medido</dt>
            <dd className="tnum font-mono text-fg">{outcome.observed_value?.toFixed(0)}%</dd>
          </div>
          {outcome.model_used && (
            <div className="flex gap-1.5">
              <dt className="text-fg-3">previsto por</dt>
              <dd className="font-mono text-fg-3">{outcome.model_used}</dd>
            </div>
          )}
        </dl>
      )}
    </Panel>
  );
}
