import { useCallback, useEffect, useState } from "react";
import { format } from "date-fns";
import { ptBR } from "date-fns/locale";
import { Tag } from "lucide-react";
import { machinesApi, errorMessage } from "../../services/api";
import { useToast } from "../ui/Toast";

interface Session {
  id: number;
  label: string;
  name: string;
  started_at: string;
  ended_at: string | null;
  source: string;
}

interface LabelState {
  catalog: { id: string; name: string }[];
  open: Session | null;
}

/**
 * Só registra o gabarito com que a avaliação em dado real mede acertos e alarmes falsos.
 * Não muda os avisos: para isso existe o modo atividade pesada.
 */
export function ActivityLabelControl({ machineId }: { machineId: number }) {
  const toast = useToast();
  const [state, setState] = useState<LabelState | null>(null);
  const [choice, setChoice] = useState("");
  const [busy, setBusy] = useState(false);

  const load = useCallback(() => {
    machinesApi.activityLabels(machineId, 1).then((r) => setState(r.data)).catch(() => {});
  }, [machineId]);

  useEffect(load, [load]);

  const mark = async (label: string) => {
    setBusy(true);
    try {
      await machinesApi.markActivity(machineId, label);
      toast.success(label === "parar" ? "Marcação encerrada." : "Marcado.");
      setChoice("");
      load();
    } catch (err) {
      toast.error(errorMessage(err));
    } finally {
      setBusy(false);
    }
  };

  if (!state) return null;

  if (state.open) {
    return (
      <div className="inline-flex items-center gap-2 text-xs text-fg-2">
        <Tag size={12} aria-hidden="true" />
        <span>
          Marcado: <span className="font-medium text-fg">{state.open.name}</span> desde{" "}
          {format(new Date(state.open.started_at), "HH:mm", { locale: ptBR })}
        </span>
        <button
          type="button"
          onClick={() => mark("parar")}
          disabled={busy}
          className="rounded-control border border-edge px-2 py-0.5 text-fg-2 transition-colors hover:bg-raised hover:text-fg"
        >
          Parar
        </button>
      </div>
    );
  }

  return (
    <div className="inline-flex items-center gap-2">
      <select
        value={choice}
        onChange={(e) => setChoice(e.target.value)}
        aria-label="O que estou fazendo agora"
        title="Só registra o que você está fazendo, para medir os acertos do sistema. Não muda os avisos."
        className="h-8 rounded-control border border-edge bg-surface px-2 text-sm text-fg focus:border-accent"
      >
        <option value="">O que estou fazendo…</option>
        {state.catalog.map((c) => (
          <option key={c.id} value={c.id}>
            {c.name}
          </option>
        ))}
      </select>
      <button
        type="button"
        onClick={() => choice && mark(choice)}
        disabled={busy || !choice}
        className="inline-flex items-center gap-1.5 rounded-control border border-edge px-2.5 py-1 text-xs text-fg-2 transition-colors hover:bg-raised hover:text-fg disabled:opacity-50"
      >
        <Tag size={12} aria-hidden="true" />
        Marcar
      </button>
    </div>
  );
}
