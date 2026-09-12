import { useEffect, useState } from "react";
import { useParams } from "react-router-dom";
import { shareApi } from "../services/api";
import { Panel, DataList, DataRow } from "../components/ui/Layout";
import { Skeleton } from "../components/ui/Skeleton";
import { EmptyState } from "../components/ui/EmptyState";
import { SignalMark } from "../components/ui/SignalMark";
import { format } from "date-fns";
import { ptBR } from "date-fns/locale";

/**
 * Página pública do pacote para o técnico. Sem login: quem recebeu o link vê
 * o incidente completo, somente leitura. É o outro lado do "gerar link".
 */
export function SharedView() {
  const { token } = useParams<{ token: string }>();
  const [pkg, setPkg] = useState<any>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    if (!token) return;
    shareApi.view(token).then((r) => setPkg(r.data)).catch(() => setPkg(null)).finally(() => setLoading(false));
  }, [token]);

  return (
    <div className="min-h-screen bg-canvas">
      <header className="flex h-14 items-center gap-2.5 border-b border-hairline px-4">
        <SignalMark className="text-accent" />
        <span className="text-sm font-semibold tracking-tight text-fg">AnomalyDetect</span>
        <span className="ml-auto text-xs text-fg-3">Diagnóstico compartilhado · somente leitura</span>
      </header>
      <main className="mx-auto max-w-3xl px-4 py-8">
        {loading ? (
          <div className="space-y-4"><Skeleton className="h-8 w-64" /><Skeleton className="h-32 w-full rounded-panel" /></div>
        ) : !pkg ? (
          <EmptyState title="Link indisponível" body="Este link expirou, foi revogado, ou nunca existiu." />
        ) : (
          <SharedContent pkg={pkg} />
        )}
      </main>
    </div>
  );
}

function SharedContent({ pkg }: { pkg: any }) {
  const a = pkg.anomaly;
  const exp = pkg.explanation;
  return (
    <div className="space-y-8">
      <header>
        <p className="channel-label">Detectado em {a.detected_at && format(new Date(a.detected_at), "dd/MM/yyyy 'às' HH:mm", { locale: ptBR })}</p>
        <h1 className="mt-1.5 text-lg font-semibold text-fg">{a.type_label}</h1>
        <p className="mt-1 text-sm text-fg-3">
          {pkg.machine.name} · {pkg.machine.os} · severidade {a.severity_label}
          {a.responsible_process && <> · <span className="font-mono text-fg-2">{a.responsible_process}</span></>}
        </p>
      </header>

      {exp && (
        <section>
          <p className="max-w-prose text-md leading-relaxed text-fg">{exp.summary}</p>
          {exp.detailed && <p className="mt-3 max-w-prose whitespace-pre-line text-sm leading-relaxed text-fg-2">{exp.detailed}</p>}
        </section>
      )}

      {exp?.causes?.length > 0 && (
        <section>
          <h2 className="channel-label mb-2">Causas prováveis</h2>
          <ol className="space-y-1.5">{exp.causes.map((c: string, i: number) => <li key={i} className="text-sm text-fg-2">{c}</li>)}</ol>
        </section>
      )}

      {exp?.recommendations?.length > 0 && (
        <section>
          <h2 className="channel-label mb-2">O que já foi orientado</h2>
          <ol className="space-y-1.5">{exp.recommendations.map((r: string, i: number) => <li key={i} className="text-sm text-fg-2">{i + 1}. {r}</li>)}</ol>
        </section>
      )}

      {pkg.metric && (
        <section>
          <h2 className="channel-label mb-2">Leitura no momento</h2>
          <Panel className="px-4 py-2">
            <DataList>
              <DataRow label="Processador" value={`${pkg.metric.cpu?.toFixed(0)}%`} />
              <DataRow label="Memória" value={`${pkg.metric.mem?.toFixed(0)}%`} />
              <DataRow label="Disco" value={`${pkg.metric.disk?.toFixed(0)}%`} />
              <DataRow label="Conexões de rede" value={pkg.metric.connections ?? "--"} />
            </DataList>
          </Panel>
        </section>
      )}

      {pkg.top_processes?.length > 0 && (
        <section>
          <h2 className="channel-label mb-2">Programas em execução</h2>
          <div className="overflow-x-auto">
            <table className="w-full text-left text-xs">
              <thead className="text-fg-3">
                <tr><th className="py-1 pr-4">Programa</th><th className="py-1 pr-4">CPU</th><th className="py-1 pr-4">RAM</th><th className="py-1">Assinatura</th></tr>
              </thead>
              <tbody className="font-mono text-fg-2">
                {pkg.top_processes.map((p: any, i: number) => (
                  <tr key={i} className="border-t border-hairline">
                    <td className="py-1 pr-4">{p.name}</td>
                    <td className="py-1 pr-4">{p.cpu?.toFixed(0)}%</td>
                    <td className="py-1 pr-4">{p.mem?.toFixed(1)}%</td>
                    <td className="py-1">{p.signed ?? "?"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </section>
      )}

      {pkg.incident?.narrative && (
        <section>
          <h2 className="channel-label mb-2">Cadeia de causa</h2>
          <p className="max-w-prose text-sm leading-relaxed text-fg-2">{pkg.incident.narrative}</p>
        </section>
      )}
    </div>
  );
}
