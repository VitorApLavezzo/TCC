import { useCallback, useEffect, useState } from "react";
import { errorMessage, machinesApi, playbooksApi } from "../../services/api";
import { ANOMALY_TYPE_LABELS } from "../../types";
import { Section, Panel } from "../ui/Layout";
import { Button } from "../ui/Button";
import { EmptyState } from "../ui/EmptyState";
import { Skeleton } from "../ui/Skeleton";
import { useToast } from "../ui/Toast";
import { useConfirm } from "../ui/ConfirmDialog";

type Playbook = {
  id: number;
  name: string;
  machine_id: number | null;
  anomaly_type: string;
  anomaly_label: string;
  action: string;
  action_label: string;
  autonomy: "sugerir" | "confirmar" | "automatico";
  autonomy_label: string;
  dry_run: boolean;
  enabled: boolean;
  runs_total: number;
  daily_limit: number;
};

type Option = { value: string; label: string };

// Só desempenho com programa responsável claro: encerrar sozinho um processo suspeito
// de segurança pode destruir a evidência do que aconteceu.
const AUTOMATABLE_TYPES = [
  "high_memory",
  "high_cpu",
  "memory_leak",
  "cpu_loop",
  "resource_abuse",
  "resource_exhaustion",
  "disk_full",
];

const select =
  "h-9 w-full rounded-control border border-edge bg-surface px-2 text-sm text-fg focus:border-accent";

/** Automação com autonomia graduada: uma regra nova nasce no degrau mais tímido; subir é escolha da pessoa. */
export function Playbooks() {
  const toast = useToast();
  const confirm = useConfirm();
  const [playbooks, setPlaybooks] = useState<Playbook[]>([]);
  const [actions, setActions] = useState<Option[]>([]);
  const [autonomies, setAutonomies] = useState<Option[]>([]);
  const [machines, setMachines] = useState<{ id: number; name: string }[]>([]);
  const [loading, setLoading] = useState(true);
  const [creating, setCreating] = useState(false);
  const [form, setForm] = useState({
    name: "",
    anomaly_type: AUTOMATABLE_TYPES[0],
    action: "kill_process",
    machine_id: "",
    dry_run: true,
  });

  const load = useCallback(async () => {
    try {
      const [r, m] = await Promise.all([playbooksApi.list(), machinesApi.list()]);
      setPlaybooks(r.data.playbooks);
      setActions(r.data.actions);
      setAutonomies(r.data.autonomies);
      setMachines(m.data.map((x: any) => ({ id: x.id, name: x.name })));
    } catch {
      setPlaybooks([]);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  async function createPlaybook() {
    if (!form.name.trim()) {
      toast.error("Dê um nome à automação.", "Por exemplo: “Fechar o navegador travado”.");
      return;
    }
    setCreating(true);
    try {
      await playbooksApi.create({
        name: form.name.trim(),
        anomaly_type: form.anomaly_type,
        action: form.action,
        machine_id: form.machine_id ? Number(form.machine_id) : null,
        dry_run: form.dry_run,
        autonomy: "sugerir",
      });
      setForm({ ...form, name: "" });
      toast.success("Automação criada em modo “só sugerir”.", "Suba o nível quando confiar nela.");
      load();
    } catch (e) {
      toast.error(errorMessage(e));
    } finally {
      setCreating(false);
    }
  }

  async function updatePlaybook(playbook: Playbook, changes: Partial<Playbook>) {
    // O modo automático faz a máquina agir sem ninguém olhando: pede confirmação explícita.
    if (changes.autonomy === "automatico") {
      const ok = await confirm({
        title: "Deixar esta automação agir sozinha?",
        body: (
          <>
            <strong>{playbook.name}</strong> vai executar “{playbook.action_label.toLowerCase()}”
            sem pedir nada, sempre que o aviso acontecer. Você é avisado antes e tem alguns minutos
            para cancelar cada execução.
          </>
        ),
        confirmLabel: "Deixar agir sozinha",
      });
      if (!ok) return;
    }
    try {
      await playbooksApi.update(playbook.id, changes);
      load();
    } catch (e) {
      toast.error(errorMessage(e));
    }
  }

  async function removePlaybook(playbook: Playbook) {
    const ok = await confirm({
      title: "Apagar esta automação?",
      body: <><strong>{playbook.name}</strong> deixa de existir. O histórico do que ela já fez continua no registro.</>,
      confirmLabel: "Apagar",
      destructive: true,
    });
    if (!ok) return;
    try {
      await playbooksApi.remove(playbook.id);
      load();
    } catch (e) {
      toast.error(errorMessage(e));
    }
  }

  if (loading) return <Skeleton className="h-40" />;

  return (
    <Section
      title="Automações"
      description="O que o sistema pode fazer sozinho quando um aviso se repete — e com quanta liberdade"
    >
      {playbooks.length === 0 ? (
        <EmptyState
          title="Nenhuma automação ainda"
          body="Crie uma regra para o sistema propor (ou executar) a ação certa da próxima vez que um aviso conhecido voltar."
        />
      ) : (
        <ul className="space-y-2">
          {playbooks.map((p) => (
            <li key={p.id}>
              <Panel className="p-3">
                <div className="flex flex-wrap items-start justify-between gap-x-4 gap-y-2">
                  <div className="min-w-0">
                    <p className="font-display text-sm font-semibold text-fg">{p.name}</p>
                    <p className="mt-0.5 text-xs text-fg-3">
                      Quando: {p.anomaly_label} · Faz: {p.action_label}
                      {p.machine_id ? "" : " · Em todos os computadores"}
                      {p.dry_run ? " · Só ensaio" : ""}
                    </p>
                  </div>
                  <div className="flex flex-shrink-0 flex-wrap items-center gap-2">
                    <label className="sr-only" htmlFor={`autonomia-${p.id}`}>
                      Autonomia de {p.name}
                    </label>
                    <select
                      id={`autonomia-${p.id}`}
                      value={p.autonomy}
                      onChange={(e) => updatePlaybook(p, { autonomy: e.target.value as Playbook["autonomy"] })}
                      className="h-8 rounded-control border border-edge bg-surface px-2 text-xs text-fg focus:border-accent"
                    >
                      {autonomies.map((a) => (
                        <option key={a.value} value={a.value}>
                          {a.label}
                        </option>
                      ))}
                    </select>
                    <Button size="sm" variant="quiet" onClick={() => updatePlaybook(p, { enabled: !p.enabled })}>
                      {p.enabled ? "Pausar" : "Retomar"}
                    </Button>
                    <Button size="sm" variant="danger" onClick={() => removePlaybook(p)}>
                      Apagar
                    </Button>
                  </div>
                </div>
                <p className="mt-2 text-micro text-fg-3">
                  {p.enabled ? "Ativa" : "Pausada"} · {p.runs_total} disparo(s) · teto de {p.daily_limit} por dia
                </p>
              </Panel>
            </li>
          ))}
        </ul>
      )}

      <Panel tone="sunken" className="mt-4 p-4">
        <p className="channel-label">Nova automação</p>
        <div className="mt-3 grid gap-3 sm:grid-cols-2">
          <label className="text-xs text-fg-2">
            Nome
            <input
              value={form.name}
              onChange={(e) => setForm({ ...form, name: e.target.value })}
              placeholder="Fechar o navegador travado"
              className="mt-1 h-9 w-full rounded-control border border-edge bg-surface px-2 text-sm text-fg focus:border-accent"
            />
          </label>
          <label className="text-xs text-fg-2">
            Quando acontecer
            <select
              value={form.anomaly_type}
              onChange={(e) => setForm({ ...form, anomaly_type: e.target.value })}
              className={`mt-1 ${select}`}
            >
              {AUTOMATABLE_TYPES.map((t) => (
                <option key={t} value={t}>
                  {ANOMALY_TYPE_LABELS[t] || t}
                </option>
              ))}
            </select>
          </label>
          <label className="text-xs text-fg-2">
            Fazer
            <select
              value={form.action}
              onChange={(e) => setForm({ ...form, action: e.target.value })}
              className={`mt-1 ${select}`}
            >
              {actions.map((a) => (
                <option key={a.value} value={a.value}>
                  {a.label}
                </option>
              ))}
            </select>
          </label>
          <label className="text-xs text-fg-2">
            Em qual computador
            <select
              value={form.machine_id}
              onChange={(e) => setForm({ ...form, machine_id: e.target.value })}
              className={`mt-1 ${select}`}
            >
              <option value="">Todos</option>
              {machines.map((m) => (
                <option key={m.id} value={m.id}>
                  {m.name}
                </option>
              ))}
            </select>
          </label>
        </div>
        <label className="mt-3 flex items-center gap-2 text-xs text-fg-2">
          <input
            type="checkbox"
            checked={form.dry_run}
            onChange={(e) => setForm({ ...form, dry_run: e.target.checked })}
            className="h-4 w-4 accent-accent"
          />
          Começar em ensaio (registra o que faria, sem fazer)
        </label>
        <Button className="mt-3" variant="primary" loading={creating} onClick={createPlaybook}>
          Criar automação
        </Button>
        <p className="mt-2 max-w-prose text-micro leading-relaxed text-fg-3">
          Toda automação nasce em “só sugerir”. Você sobe o nível na lista acima quando estiver
          seguro — e mesmo no nível automático, cada execução é anunciada antes e pode ser
          cancelada.
        </p>
      </Panel>
    </Section>
  );
}
