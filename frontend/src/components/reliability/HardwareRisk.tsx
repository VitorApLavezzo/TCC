import { useEffect, useState } from "react";
import { reliabilityApi } from "../../services/api";
import { Section, Panel, StatusDot } from "../ui/Layout";
import { Disclosure } from "../ui/Disclosure";
import { Skeleton } from "../ui/Skeleton";
import { LoadError } from "../ui/LoadError";

type Factor = { peso: number; titulo: string; detalhe: string };
type Risk = {
  component: string;
  component_label: string;
  risk_pct: number;
  horizon_days: number;
  level: "baixo" | "atencao" | "alto" | "critico";
  level_label: string;
  factors: Factor[];
  advice: string;
  sentence: string;
};

const TONE: Record<string, "ok" | "warn" | "crit"> = {
  baixo: "ok",
  atencao: "warn",
  alto: "warn",
  critico: "crit",
};

/**
 * Risco de falha das peças (SMART, bateria, erros de hardware) como a decisão a
 * tomar — fazer backup hoje ou não —, com a conta aberta embaixo.
 */
export function HardwareRisk({ machineId }: { machineId: number }) {
  const [risks, setRisks] = useState<Risk[] | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(false);

  useEffect(() => {
    let alive = true;
    reliabilityApi
      .hardwareRisk(machineId)
      .then((r) => alive && setRisks(r.data?.risks ?? []))
      .catch(() => alive && setError(true))
      .finally(() => alive && setLoading(false));
    return () => {
      alive = false;
    };
  }, [machineId]);

  if (error) return <LoadError what="o risco de falha das peças" onRetry={() => window.location.reload()} />;
  if (loading) return <Skeleton className="h-24" />;
  // Sem SMART nem bateria (uma máquina virtual, por exemplo) não há o que dizer.
  if (!risks || risks.length === 0) return null;

  return (
    <Section
      className="animate-fade"
      title="Saúde das peças"
      description={`Chance estimada de dar problema nos próximos ${risks[0].horizon_days} dias`}
    >
      <div className="space-y-3">
        {risks.map((risk) => (
          <Panel key={risk.component} className="p-4">
            <div className="flex flex-wrap items-baseline justify-between gap-x-4 gap-y-1">
              <p className="flex items-center gap-2 font-display text-sm font-semibold text-fg">
                <StatusDot tone={TONE[risk.level] ?? "idle"} />
                {risk.component_label}
              </p>
              <span className="tnum font-mono text-sm text-fg">
                {risk.risk_pct.toFixed(0)}%
                <span className="ml-2 text-micro text-fg-3">{risk.level_label}</span>
              </span>
            </div>
            <p className="mt-2 max-w-prose text-sm leading-relaxed text-fg-2">{risk.advice}</p>

            {risk.factors.length > 0 && (
              <Disclosure title={`O que pesou nessa conta (${risk.factors.length})`} className="mt-3">
                <ul className="space-y-2">
                  {risk.factors.map((f) => (
                    <li key={f.titulo}>
                      <p className="text-xs font-semibold text-fg-2">{f.titulo}</p>
                      <p className="text-xs leading-relaxed text-fg-3">{f.detalhe}</p>
                    </li>
                  ))}
                </ul>
                <p className="mt-3 text-micro leading-relaxed text-fg-3">
                  A estimativa combina os sinais acima com pesos fixos, calibrados de forma
                  conservadora. Serve para decidir se vale fazer backup agora — não é uma data de
                  validade da peça.
                </p>
              </Disclosure>
            )}
          </Panel>
        ))}
      </div>
    </Section>
  );
}
