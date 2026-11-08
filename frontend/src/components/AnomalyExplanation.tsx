// Passos são sequência a executar; causas são hipóteses por probabilidade: formas distintas.

/** Prefixos de probabilidade escritos pela IA. "menos provável" vem antes de "provável", senão nunca casa. */
const LIKELIHOOD = [
  { re: /^\s*menos\s+prov[áa]vel\s*:\s*/i, label: "Menos provável", strength: 1 },
  { re: /^\s*mais\s+prov[áa]vel\s*:\s*/i, label: "Mais provável", strength: 3 },
  { re: /^\s*poss[íi]vel\s*:\s*/i, label: "Possível", strength: 2 },
];

function parseCause(raw: string): { label: string | null; strength: number; text: string } {
  for (const { re, label, strength } of LIKELIHOOD) {
    if (re.test(raw)) return { label, strength, text: raw.replace(re, "") };
  }
  // A análise local de reserva não usa prefixo; inventar ranking pela posição seria afirmar o que não sabemos.
  return { label: null, strength: 0, text: raw };
}

/** Sem cor: probabilidade não é estado de saúde. */
function Strength({ level }: { level: number }) {
  return (
    <span className="flex gap-[3px]" aria-hidden="true">
      {[1, 2, 3].map((i) => (
        <span key={i} className={`h-[3px] w-2.5 rounded-full ${i <= level ? "bg-fg-2" : "bg-hairline"}`} />
      ))}
    </span>
  );
}

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
