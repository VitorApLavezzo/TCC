import { useCallback, useState } from "react";
import { useNavigate } from "react-router-dom";
import { BrainCircuit, CheckCircle2, Gauge, ListChecks } from "lucide-react";
import { machinesApi, errorMessage } from "../services/api";
import { usePolling } from "../hooks/usePolling";
import { Machine } from "../types";
import { Panel } from "../components/ui/Layout";
import { Button, TextButton } from "../components/ui/Button";
import { useToast } from "../components/ui/Toast";
import { EnrollPanel, EnrollCode } from "../components/machines/EnrollPanel";

const WHAT_IT_DOES = [
  {
    icon: Gauge,
    title: "Acompanha",
    body: "Processador, memória, disco, rede, temperatura e bateria, a cada poucos segundos.",
  },
  {
    icon: BrainCircuit,
    title: "Aprende",
    body: "O que é normal naquele computador, em vez de usar um limite genérico igual para todos.",
  },
  {
    icon: ListChecks,
    title: "Explica",
    body: "A causa provável quando algo sai do normal e o que fazer, passo a passo.",
  },
];

/** A ordem importa: é o caminho real da instalação. */
const STEPS = [
  "Gere o código de instalação aqui.",
  "Baixe o arquivo e execute no computador que quer monitorar.",
  "Ele aparece nesta tela sozinho, em cerca de dois minutos.",
];

/** Primeiro uso: quando a primeira máquina se registra, mostra a confirmação e leva ao painel. */
export function Welcome() {
  const navigate = useNavigate();
  const toast = useToast();
  const [machines, setMachines] = useState<Machine[]>([]);
  const [enrollCode, setEnrollCode] = useState<EnrollCode | null>(null);
  const [generating, setGenerating] = useState(false);

  const fetchMachines = useCallback(async () => {
    const res = await machinesApi.list();
    setMachines(res.data);
  }, []);

  // 10s: enquanto a pessoa instala do outro lado, a chegada precisa ser rápida.
  usePolling(fetchMachines, 10000);

  const generateCode = async () => {
    setGenerating(true);
    try {
      const res = await machinesApi.createEnrollCode();
      setEnrollCode(res.data);
    } catch (err) {
      toast.error(errorMessage(err, "Não foi possível gerar o código."));
    } finally {
      setGenerating(false);
    }
  };

  const connected = machines[0];

  if (connected) {
    return (
      <Panel className="flex flex-col gap-5 p-6 sm:flex-row sm:items-center sm:p-8">
        <CheckCircle2 size={40} className="flex-shrink-0 text-ok" aria-hidden="true" />
        <div className="min-w-0 flex-1">
          <h1 className="font-display text-xl font-semibold tracking-tight text-fg">{connected.name} está conectado</h1>
          <p className="mt-2 max-w-prose text-sm leading-relaxed text-fg-2">
            As leituras já começaram a chegar. Nas próximas horas o sistema aprende o que é normal neste
            computador e, depois disso, passa a apontar desvios sutis, além dos problemas óbvios.
          </p>
        </div>
        <Button variant="primary" className="flex-shrink-0" onClick={() => navigate("/")}>
          Ir para o painel
        </Button>
      </Panel>
    );
  }

  return (
    <div className="space-y-6">
      <header>
        <h1 className="font-display text-xl font-semibold tracking-tight text-fg">
          Vamos conectar seu primeiro computador
        </h1>
        <p className="mt-2 max-w-prose text-sm leading-relaxed text-fg-2">
          Leva cerca de dois minutos e não exige nenhum conhecimento técnico. Depois disso o AnomalyDetect acompanha
          aquele computador sozinho e avisa em português quando algo sair do normal.
        </p>
      </header>

      <ul className="grid gap-4 md:grid-cols-3">
        {WHAT_IT_DOES.map(({ icon: Icon, title, body }) => (
          <li key={title}>
            <Panel className="flex h-full flex-col gap-3 p-5">
              <span className="flex h-10 w-10 items-center justify-center rounded-control bg-accent/15 text-accent">
                <Icon size={20} aria-hidden="true" />
              </span>
              <h2 className="font-display text-base font-semibold text-fg">{title}</h2>
              <p className="text-sm leading-relaxed text-fg-2">{body}</p>
            </Panel>
          </li>
        ))}
      </ul>

      {enrollCode ? (
        <EnrollPanel enrollCode={enrollCode} onClose={() => setEnrollCode(null)} />
      ) : (
        <div className="grid gap-4 lg:grid-cols-2">
          <Panel className="flex flex-col justify-between gap-5 p-6">
            <div>
              <h2 className="font-display text-base font-semibold text-fg">Pronto para começar?</h2>
              <p className="mt-1.5 max-w-prose text-sm leading-relaxed text-fg-2">
                Vamos gerar um código de instalação. Você baixa um arquivo, executa no computador que quer monitorar, e
                ele aparece aqui sozinho.
              </p>
            </div>
            <Button
              variant="primary"
              className="self-start"
              loading={generating}
              loadingLabel="Gerando o código..."
              onClick={generateCode}
            >
              Gerar código de instalação
            </Button>
          </Panel>

          <Panel className="p-6">
            <h2 className="font-display text-base font-semibold text-fg">Em três passos</h2>
            <ol className="mt-4 space-y-3">
              {STEPS.map((step, i) => (
                <li key={step} className="flex items-start gap-3 text-sm leading-relaxed text-fg-2">
                  <span className="tnum flex h-6 w-6 flex-shrink-0 items-center justify-center rounded-full bg-raised font-mono text-xs text-fg">
                    {i + 1}
                  </span>
                  <span className="pt-0.5">{step}</span>
                </li>
              ))}
            </ol>
          </Panel>
        </div>
      )}

      <p className="text-xs text-fg-3">
        Prefere olhar o painel primeiro? <TextButton onClick={() => navigate("/")}>Ir para o painel vazio</TextButton>
      </p>
    </div>
  );
}
