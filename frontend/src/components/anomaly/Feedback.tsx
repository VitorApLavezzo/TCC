import { useState } from "react";
import { Anomaly, SECURITY_TYPES } from "../../types";
import { anomaliesApi, errorMessage } from "../../services/api";
import { Button } from "../ui/Button";
import { useToast } from "../ui/Toast";

/**
 * O ciclo de aprendizado do aviso.
 *
 * Antes só havia "resolver". Aqui a pessoa também diz se aquilo era normal
 * para ela — e o sistema cria uma regra e afrouxa o detector — ou se era um
 * problema de verdade, ao registrar a causa. Da próxima vez a explicação já
 * começa por ela.
 */
export function Feedback({ anomaly, onChange }: { anomaly: Anomaly; onChange: (a: Anomaly) => void }) {
  const toast = useToast();
  const [busy, setBusy] = useState<string | null>(null);
  const [showResolve, setShowResolve] = useState(false);
  const [cause, setCause] = useState("");
  const isSecurity = SECURITY_TYPES.has(anomaly.anomaly_type);

  const markNormal = async (scope: "process" | "type") => {
    setBusy("normal");
    try {
      const res = await anomaliesApi.feedback(anomaly.id, "normal", { scope });
      onChange(res.data);
      toast.success(
        scope === "process" && anomaly.responsible_process
          ? `Entendido. ${anomaly.responsible_process} não vai mais gerar este aviso.`
          : "Entendido. Esse tipo de aviso foi silenciado para este computador."
      );
    } catch (err) {
      toast.error(errorMessage(err));
    } finally {
      setBusy(null);
    }
  };

  const resolveWithCause = async (verify: boolean) => {
    setBusy("resolve");
    try {
      const res = await anomaliesApi.resolve(anomaly.id, true, { cause: cause.trim() || undefined, verify });
      const withFeedback = cause.trim()
        ? (await anomaliesApi.feedback(anomaly.id, "problem", { note: cause.trim() })).data
        : res.data;
      onChange(withFeedback);
      setShowResolve(false);
      setCause("");
      toast.success(verify ? "Marcado como resolvido. Vou conferir nas próximas leituras." : "Marcado como resolvido.");
    } catch (err) {
      toast.error(errorMessage(err));
    } finally {
      setBusy(null);
    }
  };

  if (anomaly.is_resolved) return null;

  return (
    <div className="mt-5 border-t border-hairline pt-4">
      <p className="channel-label mb-2.5">O que era isso?</p>
      {!showResolve ? (
        <div className="flex flex-wrap items-center gap-2">
          <Button variant="primary" onClick={() => setShowResolve(true)}>
            Era um problema — resolvi
          </Button>
          <Button variant="secondary" loading={busy === "normal"} onClick={() => markNormal("process")}>
            {anomaly.responsible_process ? `“${anomaly.responsible_process}” é normal aqui` : "Isso é normal para mim"}
          </Button>
          {!isSecurity && anomaly.responsible_process && (
            <Button variant="quiet" loading={busy === "normal"} onClick={() => markNormal("type")}>
              Todo aviso deste tipo é normal
            </Button>
          )}
        </div>
      ) : (
        <div className="max-w-prose space-y-3">
          <label className="block text-sm text-fg-2">
            O que resolveu? <span className="text-fg-3">(opcional, mas ajuda da próxima vez)</span>
            <input
              autoFocus
              value={cause}
              onChange={(e) => setCause(e.target.value)}
              placeholder="ex: era o backup do OneDrive; reiniciei o Chrome"
              className="mt-1.5 w-full rounded-control border border-edge bg-surface px-3 py-2 text-sm text-fg placeholder:text-fg-3 focus:border-accent"
            />
          </label>
          <div className="flex flex-wrap gap-2">
            <Button variant="primary" loading={busy === "resolve"} onClick={() => resolveWithCause(true)}>
              Resolver e conferir sozinho
            </Button>
            <Button variant="secondary" loading={busy === "resolve"} onClick={() => resolveWithCause(false)}>
              Só resolver
            </Button>
            <Button variant="quiet" onClick={() => setShowResolve(false)}>
              Cancelar
            </Button>
          </div>
        </div>
      )}
    </div>
  );
}

/** Selo de verificação: o sistema confere sozinho se o problema sumiu. */
export function VerificationTag({ anomaly }: { anomaly: Anomaly }) {
  const status = anomaly.verification_status;
  if (!status) return null;
  const map: Record<string, { label: string; cls: string }> = {
    watching: { label: "Conferindo se resolveu…", cls: "text-fg-3" },
    confirmed: { label: "Confirmado: voltou ao normal", cls: "text-ok" },
    failed: { label: "O problema voltou — reaberto", cls: "text-crit" },
    unverifiable: { label: "Sem como conferir automaticamente", cls: "text-fg-3" },
  };
  const item = map[status];
  if (!item) return null;
  return (
    <div className="mt-3 flex items-start gap-2 text-xs">
      <span className={`mt-1.5 h-1.5 w-1.5 flex-shrink-0 rounded-full ${status === "confirmed" ? "bg-ok" : status === "failed" ? "bg-crit" : "bg-fg-3"}`} />
      <span className={item.cls}>
        {item.label}
        {anomaly.verification_note && <span className="block text-fg-3">{anomaly.verification_note}</span>}
      </span>
    </div>
  );
}
