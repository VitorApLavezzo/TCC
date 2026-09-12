import { useCallback, useState } from "react";
import { machinesApi, errorMessage } from "../services/api";
import { usePolling } from "../hooks/usePolling";
import { Machine } from "../types";
import { Button } from "../components/ui/Button";
import { PageHeader } from "../components/ui/Layout";
import { EmptyState } from "../components/ui/EmptyState";
import { ListSkeleton } from "../components/ui/Skeleton";
import { StaleBanner } from "../components/StaleBanner";
import { useToast } from "../components/ui/Toast";
import { useConfirm } from "../components/ui/ConfirmDialog";
import { EnrollPanel, EnrollCode } from "../components/machines/EnrollPanel";
import { BulkEnrollPanel } from "../components/machines/BulkEnrollPanel";
import { MachineCard } from "../components/machines/MachineCard";
import { FleetCompare } from "../components/machines/FleetCompare";
import { pluralize } from "../lib/format";

export function Machines() {
  const toast = useToast();
  const confirm = useConfirm();
  const [machines, setMachines] = useState<Machine[]>([]);
  const [enrollCode, setEnrollCode] = useState<EnrollCode | null>(null);
  const [generating, setGenerating] = useState(false);
  const [busyId, setBusyId] = useState<number | null>(null);

  const fetchMachines = useCallback(async () => {
    const res = await machinesApi.list();
    setMachines(res.data);
  }, []);

  const poll = usePolling(fetchMachines, 15000);

  const generateCode = async () => {
    setGenerating(true);
    try {
      const res = await machinesApi.createEnrollCode();
      setEnrollCode(res.data);
    } catch (err) {
      toast.error(
        errorMessage(err, "Não foi possível gerar o código."),
        "Verifique sua conexão com o servidor e tente de novo."
      );
    } finally {
      setGenerating(false);
    }
  };

  // O diálogo nomeia a máquina. O confirm() nativo dizia apenas "esta máquina",
  // o que com vários computadores na lista era risco de apagar o errado.
  const remove = async (m: Machine) => {
    const ok = await confirm({
      title: `Remover ${m.name} do painel?`,
      body: (
        <>
          Todo o histórico de <strong className="text-fg">{m.name}</strong> ({m.hostname}) será apagado — leituras e
          avisos. Isso não pode ser desfeito.
          <br />
          <br />O agente continua instalado naquele computador. Para removê-lo de verdade, use o desinstalador antes.
        </>
      ),
      confirmLabel: "Remover e apagar o histórico",
      destructive: true,
    });
    if (!ok) return;

    setBusyId(m.id);
    try {
      await machinesApi.delete(m.id);
      await fetchMachines();
      toast.success(`${m.name} foi removido do painel.`);
    } catch (err) {
      toast.error(errorMessage(err, `Não foi possível remover ${m.name}.`), "Tente de novo em alguns segundos.");
    } finally {
      setBusyId(null);
    }
  };

  const togglePause = async (m: Machine) => {
    const pausing = m.is_active;
    if (pausing) {
      const ok = await confirm({
        title: `Pausar a coleta de ${m.name}?`,
        body: (
          <>
            Enquanto estiver pausado, <strong className="text-fg">nenhum problema será detectado</strong> neste
            computador. O agente segue instalado e você pode retomar quando quiser.
          </>
        ),
        confirmLabel: "Pausar a coleta",
      });
      if (!ok) return;
    }

    setBusyId(m.id);
    try {
      await machinesApi.update(m.id, { is_active: !m.is_active });
      await fetchMachines();
      toast.success(pausing ? `Coleta de ${m.name} pausada.` : `Coleta de ${m.name} retomada.`);
    } catch (err) {
      toast.error(errorMessage(err, "Não foi possível alterar a coleta."));
    } finally {
      setBusyId(null);
    }
  };

  const paused = machines.filter((m) => !m.is_active).length;

  return (
    <div className="space-y-6">
      <StaleBanner onRetry={poll.refresh} />

      <PageHeader
        title="Computadores"
        description={
          machines.length === 0
            ? "Nenhum conectado ainda."
            : `${pluralize(machines.length, "computador conectado", "computadores conectados")}${
                paused > 0 ? ` · ${paused} com a coleta pausada` : ""
              }.`
        }
        actions={
          <Button variant="primary" loading={generating} loadingLabel="Gerando..." onClick={generateCode}>
            Conectar computador
          </Button>
        }
      />

      {enrollCode && <EnrollPanel enrollCode={enrollCode} onClose={() => setEnrollCode(null)} />}

      {poll.initialLoading ? (
        <ListSkeleton rows={2} />
      ) : machines.length === 0 ? (
        !enrollCode && (
          <EmptyState
            title="Nenhum computador conectado"
            body="Gere um código de instalação e siga os três passos. O instalador cuida de tudo — você não precisa configurar nada manualmente."
            action={
              <Button variant="primary" loading={generating} loadingLabel="Gerando..." onClick={generateCode}>
                Conectar o primeiro
              </Button>
            }
          />
        )
      ) : (
        <ul className="divide-y divide-hairline border-y border-hairline">
          {machines.map((m) => (
            <MachineCard
              key={m.id}
              machine={m}
              busy={busyId === m.id}
              onTogglePause={togglePause}
              onDelete={remove}
            />
          ))}
        </ul>
      )}

      {machines.length >= 3 && <FleetCompare />}

      <BulkEnrollPanel />
    </div>
  );
}
