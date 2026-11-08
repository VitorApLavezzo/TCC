import { useEffect, useState } from "react";
import { evaluationApi } from "../../services/api";
import { Section } from "../ui/Layout";
import { EmptyState } from "../ui/EmptyState";

type Row = {
  previsoes: number;
  medidas: number;
  acertos: number;
  taxa_acerto_pct: number | null;
  erro_medio_pontos: number | null;
};

/** Por provedor: quando a IA previu um efeito ("a memória cai para 48%"), ele aconteceu? */
export function ExplanationFidelity({ days = 90 }: { days?: number }) {
  const [data, setData] = useState<any>(null);

  useEffect(() => {
    let alive = true;
    evaluationApi
      .fidelity(days)
      .then((r) => alive && setData(r.data))
      .catch(() => alive && setData(null));
    return () => {
      alive = false;
    };
  }, [days]);

  const providers: [string, Row][] = Object.entries(data?.by_provider ?? {});

  return (
    <Section
      title="A IA acertou o que previu?"
      description="Cada “se você fechar X, cai para Y” é conferido nas leituras seguintes à ação"
    >
      {providers.length === 0 ? (
        <EmptyState
          title="Nenhuma previsão conferida ainda"
          body="Assim que alguém executar uma ação a partir de um aviso com o cartão “e se eu fechar?”, o resultado aparece aqui."
        />
      ) : (
        <>
          <div className="scroll-hint overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-hairline text-left text-micro uppercase tracking-wide text-fg-3">
                  <th className="py-2 font-medium">Provedor</th>
                  <th className="py-2 text-right font-medium">Previsões</th>
                  <th className="py-2 text-right font-medium">Conferidas</th>
                  <th className="py-2 text-right font-medium">Acertou</th>
                  <th className="py-2 text-right font-medium">Erro médio</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-hairline">
                {providers.map(([name, row]) => (
                  <tr key={name}>
                    <td className="py-2 font-mono text-xs text-fg-2">{name}</td>
                    <td className="tnum py-2 text-right font-mono text-fg-2">{row.previsoes}</td>
                    <td className="tnum py-2 text-right font-mono text-fg-2">{row.medidas}</td>
                    <td className="tnum py-2 text-right font-mono text-fg">
                      {row.taxa_acerto_pct == null ? "—" : `${row.taxa_acerto_pct}%`}
                    </td>
                    <td className="tnum py-2 text-right font-mono text-fg-2">
                      {row.erro_medio_pontos == null ? "—" : `${row.erro_medio_pontos} pts`}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <p className="mt-3 text-micro text-fg-3">
            Conta como acerto quando a medida real ficou a até {data?.tolerancia_pontos} pontos
            percentuais do previsto.
          </p>
        </>
      )}
    </Section>
  );
}
