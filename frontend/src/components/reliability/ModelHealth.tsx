import { useEffect, useState } from "react";
import { decimal } from "../../lib/format";
import { reliabilityApi } from "../../services/api";
import { Section, Panel, StatusDot } from "../ui/Layout";
import { Skeleton } from "../ui/Skeleton";
import { LoadError } from "../ui/LoadError";

type Feature = { key: string; label: string; distance: number; media_treino: number; media_recente: number };
type Drift = {
  level: "ok" | "warn" | "critical";
  label: string;
  message: string;
  distance: number;
  per_feature: Feature[];
  retrained: boolean;
  samples_recent: number;
  checked_at: string;
};

const TONE: Record<string, "ok" | "warn" | "crit"> = { ok: "ok", warn: "warn", critical: "crit" };

/**
 * Saúde do modelo desta máquina.
 *
 * Um monitor comum nunca conta ao usuário que a régua envelheceu — ele
 * simplesmente passa a errar. Aqui a deriva é dita em voz alta: o que mudou,
 * quanto mudou e o que o sistema fez a respeito.
 */
export function ModelHealth({ machineId }: { machineId: number }) {
  const [drift, setDrift] = useState<Drift | null>(null);
  const [loading, setLoading] = useState(true);
  const [erro, setErro] = useState(false);

  useEffect(() => {
    let vivo = true;
    reliabilityApi
      .drift(machineId)
      .then((r) => vivo && setDrift(r.data?.current ?? null))
      .catch(() => vivo && setErro(true))
      .finally(() => vivo && setLoading(false));
    return () => {
      vivo = false;
    };
  }, [machineId]);

  if (erro) return <LoadError what="a saúde do modelo deste computador" onRetry={() => window.location.reload()} />;
  if (loading) return <Skeleton className="h-24" />;
  // Sem medição ainda (histórico curto): a tela não precisa de uma caixa
  // dizendo que não sabe.
  if (!drift) return null;

  const mudaram = drift.per_feature.filter((f) => f.distance >= 0.1).slice(0, 3);

  return (
    <Section className="animate-fade" title="O normal aprendido" description="Se o que o modelo aprendeu ainda descreve este computador">
      <Panel className="p-4">
        <div className="flex items-baseline justify-between gap-4">
          <p className="flex items-center gap-2 font-display text-sm font-semibold text-fg">
            <StatusDot tone={TONE[drift.level] ?? "idle"} />
            {drift.label}
          </p>
          <span className="tnum font-mono text-micro text-fg-3">distância {decimal(drift.distance, 2)}</span>
        </div>
        <p className="mt-2 max-w-prose text-sm leading-relaxed text-fg-2">{drift.message}</p>

        {mudaram.length > 0 && (
          <ul className="mt-3 space-y-1 border-t border-hairline pt-3">
            {mudaram.map((f) => (
              <li key={f.key} className="flex items-baseline justify-between gap-3 text-xs">
                <span className="text-fg-2">{f.label}</span>
                <span className="tnum font-mono text-fg-3">
                  {f.media_treino.toFixed(0)} → {f.media_recente.toFixed(0)}
                </span>
              </li>
            ))}
          </ul>
        )}
        {drift.retrained && (
          <p className="mt-3 text-xs text-fg-3">
            O modelo foi treinado de novo com as leituras atuais nesta verificação.
          </p>
        )}
      </Panel>
    </Section>
  );
}
