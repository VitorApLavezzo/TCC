import { useCallback, useState } from "react";
import { useNavigate } from "react-router-dom";
import { machinesApi, errorMessage } from "../services/api";
import { usePolling } from "../hooks/usePolling";
import { Machine } from "../types";
import { Panel, DataList, DataRow } from "../components/ui/Layout";
import { Button, TextButton } from "../components/ui/Button";
import { useToast } from "../components/ui/Toast";
import { EnrollPanel, EnrollCode } from "../components/machines/EnrollPanel";

/**
 * Primeiro uso.
 *
 * Antes, quem criava a conta caía num painel vazio com um botão e nenhuma
 * explicação do que o produto faz. A página se resolve sozinha: quando a
 * primeira máquina se registra, mostra a confirmação e leva ao painel.
 */
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
      <div className="mx-auto max-w-lg py-6">
        <h1 className="text-lg font-semibold tracking-tight text-fg">{connected.name} está conectado</h1>
        <p className="mt-2 max-w-prose text-sm leading-relaxed text-fg-2">
          As leituras começam a chegar a cada 30 segundos. Nas próximas horas o sistema aprende o que é normal neste
          computador — depois disso ele passa a apontar desvios sutis, além dos problemas óbvios.
        </p>
        <Button variant="primary" className="mt-5" onClick={() => navigate("/")}>
          Ir para o painel
        </Button>
      </div>
    );
  }

  return (
    <div className="mx-auto max-w-2xl space-y-8 py-2">
      <header>
        <h1 className="text-lg font-semibold tracking-tight text-fg">Vamos conectar seu primeiro computador</h1>
        <p className="mt-2 max-w-prose text-sm leading-relaxed text-fg-2">
          Leva cerca de dois minutos e não exige nenhum conhecimento técnico. Depois disso o AnomalyDetect acompanha
          aquele computador sozinho, e avisa em português quando algo sair do normal.
        </p>
      </header>

      <Panel className="px-4 py-2">
        <DataList>
          <DataRow label="Acompanha" value="processador, memória, disco, rede, temperatura e bateria, a cada 30 s" />
          <DataRow label="Aprende" value="o que é normal naquele computador, em vez de um limite genérico" />
          <DataRow label="Explica" value="a causa provável e o que fazer, passo a passo" />
        </DataList>
      </Panel>

      {enrollCode ? (
        <EnrollPanel enrollCode={enrollCode} onClose={() => setEnrollCode(null)} />
      ) : (
        <div className="border-t border-hairline pt-5">
          <h2 className="text-base font-semibold text-fg">Pronto para começar?</h2>
          <p className="mt-1.5 max-w-prose text-sm leading-relaxed text-fg-2">
            Vamos gerar um código de instalação. Você baixa um arquivo, executa no computador que quer monitorar, e ele
            aparece aqui sozinho.
          </p>
          <Button
            variant="primary"
            className="mt-4"
            loading={generating}
            loadingLabel="Gerando o código..."
            onClick={generateCode}
          >
            Gerar código de instalação
          </Button>
        </div>
      )}

      <p className="text-xs text-fg-3">
        Prefere olhar o painel primeiro? <TextButton onClick={() => navigate("/")}>Ir para o painel vazio</TextButton>
      </p>
    </div>
  );
}
