import { useCallback, useEffect, useState } from "react";
import { auditApi, errorMessage } from "../../services/api";
import { Section, Panel, StatusDot } from "../ui/Layout";
import { Button } from "../ui/Button";
import { Disclosure } from "../ui/Disclosure";
import { useToast } from "../ui/Toast";
import { format } from "date-fns";
import { ptBR } from "date-fns/locale";

type Entry = {
  id: number;
  created_at: string;
  label: string;
  ref_id: number | null;
  short_hash: string;
  payload: Record<string, unknown>;
};

type Verification = { ok: boolean; entries: number; message: string; broken_at?: number };

/**
 * Livro de auditoria.
 *
 * Cada fato relevante entra numa cadeia em que a entrada carrega o hash da
 * anterior. Mexer num registro antigo quebra todas as contas seguintes — e é
 * isso que o botão "conferir" mostra, em uma frase. Serve para anexar a um
 * chamado, a um processo ou a uma auditoria interna.
 */
export function AuditLedger() {
  const toast = useToast();
  const [entries, setEntries] = useState<Entry[]>([]);
  const [verificacao, setVerificacao] = useState<Verification | null>(null);
  const [conferindo, setConferindo] = useState(false);

  const load = useCallback(async () => {
    try {
      const r = await auditApi.entries({ limit: 25 });
      setEntries(r.data.entries);
    } catch {
      setEntries([]);
    }
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  async function conferir() {
    setConferindo(true);
    try {
      const r = await auditApi.verify();
      setVerificacao(r.data);
    } catch (e) {
      toast.error(errorMessage(e));
    } finally {
      setConferindo(false);
    }
  }

  async function baixar() {
    try {
      const r = await auditApi.report();
      const url = URL.createObjectURL(new Blob([r.data], { type: "text/plain;charset=utf-8" }));
      const a = document.createElement("a");
      a.href = url;
      a.download = "auditoria-anomalydetect.txt";
      a.click();
      URL.revokeObjectURL(url);
    } catch (e) {
      toast.error(errorMessage(e));
    }
  }

  return (
    <Section
      title="Registro inviolável"
      description="Avisos, ações e automações lacrados em cadeia: adulterar um registro antigo fica detectável"
      actions={
        <div className="flex gap-2">
          <Button size="sm" variant="secondary" loading={conferindo} onClick={conferir}>
            Conferir a cadeia
          </Button>
          <Button size="sm" variant="quiet" onClick={baixar}>
            Baixar relatório
          </Button>
        </div>
      }
    >
      {verificacao && (
        <Panel className="mb-3 flex items-start gap-2 p-3">
          <StatusDot tone={verificacao.ok ? "ok" : "crit"} className="mt-1.5" />
          <p className="text-sm leading-relaxed text-fg-2">{verificacao.message}</p>
        </Panel>
      )}

      {entries.length === 0 ? (
        <p className="max-w-prose text-sm leading-relaxed text-fg-2">
          Nada lacrado ainda. O primeiro registro entra sozinho quando um aviso for criado ou uma ação
          for executada num computador seu.
        </p>
      ) : (
        <ul className="divide-y divide-hairline">
          {entries.map((e) => (
            <li key={e.id} className="py-2.5">
              <div className="flex flex-wrap items-baseline justify-between gap-x-4 gap-y-1">
                <p className="text-sm text-fg-2">
                  {e.label} {e.ref_id ? <span className="text-fg-3">#{e.ref_id}</span> : null}
                </p>
                <span className="tnum font-mono text-micro text-fg-3">
                  {e.created_at ? format(new Date(e.created_at), "dd/MM HH:mm", { locale: ptBR }) : "—"} ·{" "}
                  {e.short_hash}
                </span>
              </div>
              <Disclosure title="Ver o conteúdo lacrado" className="mt-1">
                <pre className="overflow-x-auto font-mono text-micro text-fg-3">
                  {JSON.stringify(e.payload, null, 2)}
                </pre>
              </Disclosure>
            </li>
          ))}
        </ul>
      )}
    </Section>
  );
}
