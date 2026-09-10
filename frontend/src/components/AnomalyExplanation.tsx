/**
 * As duas listas da explicação de um aviso.
 *
 * Elas vinham com a mesma forma — número em mono, filete entre linhas — mas
 * não são a mesma coisa. Passos são uma sequência para executar em ordem;
 * causas são hipóteses ordenadas por probabilidade, e não se "executa" uma
 * causa. Dar a mesma cara às duas fazia a página virar uma escada de faixas
 * horizontais em que nada se distinguia.
 *
 * Nenhuma das duas usa divisória: o ritmo vem do espaço e do marcador.
 */

/**
 * Rótulos de probabilidade que a IA já escreve no início de cada causa.
 *
 * A ordem importa: "menos provável" precisa ser testada antes de "provável",
 * senão o prefixo mais longo nunca casa.
 */
const LIKELIHOOD = [
  { re: /^\s*menos\s+prov[áa]vel\s*:\s*/i, label: "Menos provável", strength: 1 },
  { re: /^\s*mais\s+prov[áa]vel\s*:\s*/i, label: "Mais provável", strength: 3 },
  { re: /^\s*poss[íi]vel\s*:\s*/i, label: "Possível", strength: 2 },
];

function parseCause(raw: string): { label: string | null; strength: number; text: string } {
  for (const { re, label, strength } of LIKELIHOOD) {
    if (re.test(raw)) return { label, strength, text: raw.replace(re, "") };
  }
  // A análise local de reserva não usa prefixo. Sem ele não há ranking a
  // mostrar — inventar um a partir da posição seria afirmar o que não sabemos.
  return { label: null, strength: 0, text: raw };
}

/** Três traços preenchidos conforme a probabilidade. Sem cor: probabilidade não é estado de saúde. */
function Strength({ level }: { level: number }) {
  return (
    <span className="flex gap-[3px]" aria-hidden="true">
      {[1, 2, 3].map((i) => (
        <span key={i} className={`h-[3px] w-2.5 rounded-full ${i <= level ? "bg-fg-2" : "bg-hairline"}`} />
      ))}
    </span>
  );
}

/**
 * Os passos, como procedimento.
 *
 * Uma calha vertical liga os números, do jeito que um manual liga etapas —
 * a mesma calha da fita de eventos. Cada passo tem 250 a 350 caracteres de
 * instrução concreta, então o espaço entre eles é o que torna a lista
 * percorrível em vez de um bloco só.
 */
export function ActionSteps({ steps }: { steps: string[] }) {
  return (
    <ol className="relative">
      {steps.map((step, i) => (
        <li key={i} className="relative flex gap-4 pb-6 last:pb-0">
          <div className="relative flex w-6 flex-shrink-0 justify-center">
            <span
              className="flex h-6 w-6 items-center justify-center rounded-full border border-edge bg-surface"
              aria-hidden="true"
            >
              <span className="tnum font-mono text-micro font-medium text-fg-2">{i + 1}</span>
            </span>
            {/* A calha desce até o próximo passo; o último não continua. */}
            {i < steps.length - 1 && (
              <span className="absolute bottom-0 top-7 w-px bg-hairline" aria-hidden="true" />
            )}
          </div>
          <p className="max-w-prose pt-0.5 text-sm leading-relaxed text-fg-2">{step}</p>
        </li>
      ))}
    </ol>
  );
}

/**
 * As causas, como hipóteses classificadas.
 *
 * O rótulo de probabilidade sai do próprio texto da IA e vira coluna, em vez
 * de ficar embutido na frase — assim dá para percorrer só os rótulos e achar
 * a explicação mais plausível sem ler as três.
 */
export function RankedCauses({ causes }: { causes: string[] }) {
  const parsed = causes.map(parseCause);
  const ranked = parsed.some((c) => c.label);

  return (
    <ul className="space-y-4">
      {parsed.map((cause, i) => (
        <li key={i} className="grid gap-x-5 gap-y-1 sm:grid-cols-[8.5rem_minmax(0,1fr)]">
          {ranked ? (
            <div className="flex items-center gap-2 sm:flex-col sm:items-start sm:gap-1.5 sm:pt-0.5">
              <span className="channel-label">{cause.label ?? "Sem ordem"}</span>
              {cause.label && <Strength level={cause.strength} />}
            </div>
          ) : (
            <span className="channel-label sm:pt-0.5">Possível causa</span>
          )}
          <p className="max-w-prose text-sm leading-relaxed text-fg-2">{cause.text}</p>
        </li>
      ))}
    </ul>
  );
}
