import { useEffect, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import { demoApi, errorMessage } from "../services/api";
import { PageHeader, Section } from "../components/ui/Layout";
import { Button, TextButton } from "../components/ui/Button";
import { useToast } from "../components/ui/Toast";
import { ANOMALY_TYPE_LABELS } from "../types";

/**
 * Modo demonstração — para apresentar à banca sem travar um computador real.
 *
 * Injeta leituras sintéticas que passam pelo MESMO pipeline das reais:
 * detectores, modelo, IA, incidentes. O que aparece no painel é o que o
 * sistema de fato detectou.
 */
export function Demo() {
  const toast = useToast();
  const navigate = useNavigate();
  const [scenarios, setScenarios] = useState<any[]>([]);
  const [session, setSession] = useState<any | null>(null);
  const [starting, setStarting] = useState<string | null>(null);
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);

  useEffect(() => {
    demoApi.scenarios().then((r) => setScenarios(r.data.scenarios)).catch(() => {});
    return () => {
      if (pollRef.current) clearInterval(pollRef.current);
    };
  }, []);

  const start = async (scenario: string) => {
    setStarting(scenario);
    try {
      const res = await demoApi.start(scenario, true);
      setSession(res.data);
      pollRef.current = setInterval(async () => {
        try {
          const r = await demoApi.status(res.data.id);
          setSession(r.data);
          if (r.data.status !== "running" && pollRef.current) clearInterval(pollRef.current);
        } catch {
          /* continua */
        }
      }, 1500);
    } catch (err) {
      toast.error(errorMessage(err));
    } finally {
      setStarting(null);
    }
  };

  const cleanup = async () => {
    if (!session) return;
    try {
      await demoApi.cleanup(session.id);
      toast.success("Computador de demonstração removido.");
      setSession(null);
    } catch (err) {
      toast.error(errorMessage(err));
    }
  };

  return (
    <div className="space-y-6">
      <PageHeader
        title="Demonstração"
        description="Injeta anomalias controladas para apresentar o sistema — sem precisar travar um computador de verdade. As leituras passam pela mesma detecção das reais."
      />

      {!session ? (
        <Section title="Escolha um cenário">
          <div className="grid grid-cols-1 gap-2 sm:grid-cols-2">
            {scenarios.map((s) => (
              <button
                key={s.id}
                type="button"
                disabled={starting !== null}
                onClick={() => start(s.id)}
                className="rounded-panel border border-hairline bg-surface px-4 py-3 text-left transition-colors hover:border-edge disabled:opacity-50"
              >
                <p className="text-sm font-medium text-fg">{s.label}</p>
                <p className="mt-0.5 text-xs text-fg-3">
                  {starting === s.id ? "Iniciando…" : `${s.steps} leituras · espera detectar ${ANOMALY_TYPE_LABELS[s.expect] ?? s.expect}`}
                </p>
              </button>
            ))}
          </div>
        </Section>
      ) : (
        <div className="space-y-5">
          <div className="rounded-panel border border-hairline bg-surface px-5 py-4">
            <div className="flex items-center justify-between gap-3">
              <p className="text-sm font-medium text-fg">
                {scenarios.find((s) => s.id === session.scenario)?.label ?? session.scenario}
              </p>
              <span className="text-xs text-fg-3">
                {session.status === "running" ? "rodando…" : session.status === "done" ? "concluído" : session.status}
              </span>
            </div>
            <div className="mt-3 h-1 overflow-hidden rounded-full bg-sunken">
              <div className="h-full bg-accent transition-[width] duration-500" style={{ width: `${(session.step / session.total_steps) * 100}%` }} />
            </div>
            <p className="tnum mt-1.5 font-mono text-micro text-fg-3">{session.step} de {session.total_steps} leituras</p>
          </div>

          <Section title="O que o sistema detectou" description="Ao vivo, conforme as leituras chegam">
            {session.log?.length ? (
              <ul className="space-y-1.5 font-mono text-xs text-fg-2">
                {session.log.map((l: string, i: number) => (
                  <li key={i} className={l.includes("detectado") ? "text-crit" : "text-fg-3"}>{l}</li>
                ))}
              </ul>
            ) : (
              <p className="text-sm text-fg-3">Aguardando as primeiras leituras…</p>
            )}
          </Section>

          <div className="flex flex-wrap gap-2">
            {session.machine_ids?.[0] && (
              <Button variant="primary" onClick={() => navigate(`/anomalies?machine_id=${session.machine_ids[0]}`)}>
                Ver os avisos gerados
              </Button>
            )}
            <Button variant="danger" onClick={cleanup}>Encerrar e remover a demonstração</Button>
            <TextButton onClick={() => setSession(null)}>Voltar aos cenários</TextButton>
          </div>
        </div>
      )}
    </div>
  );
}
