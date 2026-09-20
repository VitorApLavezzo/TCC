import { Incident } from "../../types";

/**
 * A cadeia de causa e efeito de um incidente.
 *
 * Vários sintomas que aconteceram juntos, ligados por setas de "porque". Em
 * vez de três avisos soltos — disco cheio, memória virtual, lentidão — uma
 * história só, lida de cima para baixo: a causa provável no topo, o efeito
 * sentido embaixo.
 */
export function IncidentChain({ incident }: { incident: Incident }) {
  const nodes = incident.chain?.nodes ?? [];
  if (nodes.length < 2) return null;

  const roleTone: Record<string, string> = {
    "causa provável": "text-crit",
    efeito: "text-fg",
    sintoma: "text-fg-2",
  };

  return (
    <div>
      <ol className="relative space-y-0">
        {/*
          Os elos aparecem em sequência, e não de uma vez: a ordem da animação
          é a ordem causal — disco cheio, depois memória virtual, depois
          lentidão. É a única animação do produto que carrega o argumento, não
          só a estética. Quem pediu menos movimento no sistema recebe tudo de
          uma vez, pela regra global de prefers-reduced-motion.
        */}
        {nodes.map((node, i) => (
          <li
            key={node.signal}
            className="animate-rise relative flex gap-3.5 pb-5 last:pb-0"
            style={{ animationDelay: `${i * 130}ms` }}
          >
            <div className="relative flex w-4 flex-shrink-0 justify-center">
              <span
                className={`mt-1 h-[9px] w-[9px] flex-shrink-0 rotate-45 ${
                  node.role === "causa provável" ? "bg-crit" : i === nodes.length - 1 ? "bg-accent" : "bg-fg-3"
                }`}
                aria-hidden="true"
              />
              {i < nodes.length - 1 && <span className="absolute bottom-0 top-4 w-px bg-hairline" aria-hidden="true" />}
            </div>
            <div className="min-w-0 pt-0.5">
              <p className={`text-sm ${roleTone[node.role] ?? "text-fg-2"}`}>
                {node.label.charAt(0).toUpperCase() + node.label.slice(1)}
              </p>
              <p className="channel-label mt-0.5">{node.role}</p>
            </div>
          </li>
        ))}
      </ol>
      {incident.narrative && (
        <p className="mt-3 max-w-prose border-l-2 border-hairline pl-3 text-xs leading-relaxed text-fg-3">
          {incident.narrative}
        </p>
      )}
    </div>
  );
}
