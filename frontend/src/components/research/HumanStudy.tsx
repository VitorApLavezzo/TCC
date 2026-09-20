import { useCallback, useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { errorMessage, studyApi } from "../../services/api";
import { Section, Panel } from "../ui/Layout";
import { Button } from "../ui/Button";
import { EmptyState } from "../ui/EmptyState";
import { useToast } from "../ui/Toast";

type Arm = {
  respostas: number;
  acertos: number;
  acerto_pct: number | null;
  tempo_mediano_s: number | null;
  confianca_media: number | null;
};

type Results = {
  participantes: number;
  concluidos: number;
  respostas: number;
  com_explicacao: Arm;
  sem_explicacao: Arm;
  p_acerto: number | null;
  p_tempo: number | null;
  sus_media: number | null;
  sus_n: number;
  sentence: string;
};

const num = (v: number | null | undefined, sufixo = "") => (v == null ? "—" : `${v}${sufixo}`);

/**
 * Resultado do estudo com pessoas.
 *
 * É a única seção desta página em que o dado não vem do sistema medindo a si
 * mesmo. Duas condições, mesmo participante, tempo e acerto cronometrados —
 * e o p-valor ao lado, para a conclusão não depender de quem está lendo.
 */
export function HumanStudy() {
  const toast = useToast();
  const [results, setResults] = useState<Results | null>(null);

  const load = useCallback(async () => {
    try {
      const r = await studyApi.results();
      setResults(r.data);
    } catch {
      setResults(null);
    }
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  async function baixar() {
    try {
      const r = await studyApi.exportCsv();
      const url = URL.createObjectURL(new Blob([r.data], { type: "text/csv;charset=utf-8" }));
      const a = document.createElement("a");
      a.href = url;
      a.download = "estudo-compreensao.csv";
      a.click();
      URL.revokeObjectURL(url);
    } catch (e) {
      toast.error(errorMessage(e));
    }
  }

  const vazio = !results || results.respostas === 0;

  return (
    <Section
      title="Estudo com pessoas"
      description="A explicação faz diferença para quem não é da área? Mesmos avisos, metade com explicação, metade só com os números"
      actions={
        <div className="flex gap-2">
          <Link to="/estudo">
            <Button size="sm" variant="primary">
              Aplicar a alguém
            </Button>
          </Link>
          {!vazio && (
            <Button size="sm" variant="quiet" onClick={baixar}>
              Baixar CSV
            </Button>
          )}
        </div>
      }
    >
      {vazio ? (
        <EmptyState
          title="Nenhuma sessão registrada"
          body="Cada participante responde a seis avisos reais, metade com explicação da IA. O sistema cronometra e compara."
        />
      ) : (
        <>
          <div className="grid gap-3 sm:grid-cols-2">
            {([["Com explicação", results!.com_explicacao], ["Só com os números", results!.sem_explicacao]] as const).map(
              ([titulo, arm]) => (
                <Panel key={titulo} className="p-4">
                  <p className="channel-label">{titulo}</p>
                  <p className="tnum mt-2 font-mono text-xl text-fg">{num(arm.acerto_pct, "%")}</p>
                  <p className="text-xs text-fg-3">identificaram o problema corretamente</p>
                  <dl className="mt-3 space-y-1 border-t border-hairline pt-3 text-xs">
                    <div className="flex justify-between gap-3">
                      <dt className="text-fg-2">Tempo mediano</dt>
                      <dd className="tnum font-mono text-fg">{num(arm.tempo_mediano_s, " s")}</dd>
                    </div>
                    <div className="flex justify-between gap-3">
                      <dt className="text-fg-2">Confiança média (1 a 5)</dt>
                      <dd className="tnum font-mono text-fg">{num(arm.confianca_media)}</dd>
                    </div>
                    <div className="flex justify-between gap-3">
                      <dt className="text-fg-2">Respostas</dt>
                      <dd className="tnum font-mono text-fg-2">{arm.respostas}</dd>
                    </div>
                  </dl>
                </Panel>
              )
            )}
          </div>

          <p className="mt-4 max-w-prose text-sm leading-relaxed text-fg-2">{results!.sentence}</p>
          <p className="mt-2 text-micro text-fg-3">
            {results!.participantes} participante(s), {results!.concluidos} concluído(s)
            {results!.p_acerto != null && ` · p (acerto) = ${results!.p_acerto.toFixed(3)}`}
            {results!.p_tempo != null && ` · p (tempo) = ${results!.p_tempo.toFixed(3)}`}
            {results!.sus_media != null && ` · SUS ${results!.sus_media} (n = ${results!.sus_n})`}
          </p>
        </>
      )}
    </Section>
  );
}
