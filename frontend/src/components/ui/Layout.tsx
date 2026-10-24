import { clsx } from "clsx";
import { ReactNode } from "react";

/**
 * Sistema de estrutura da página.
 *
 * A regra: seções são separadas por filete e espaço, não por caixas. Painel
 * com borda fica reservado a conteúdo que é mesmo um objeto — uma linha de
 * lista clicável, um estado da tela.
 *
 * A outra regra, tipográfica, atravessa todos estes componentes: título em
 * Red Hat Display, prosa em Red Hat Text, e tudo que a máquina mediu em Red
 * Hat Mono. Um valor sempre parece um valor, mesmo fora de contexto.
 */

/** Cabeçalho da página: título, apoio e ação principal, fechado por filete. */
export function PageHeader({
  title,
  description,
  actions,
  aside,
}: {
  title: string;
  description?: string;
  /** Ação principal, à direita. No máximo uma por página. */
  actions?: ReactNode;
  /** Controle contextual (seletor de máquina, por exemplo). */
  aside?: ReactNode;
}) {
  return (
    <header className="border-b border-hairline pb-4">
      <div className="flex flex-wrap items-start justify-between gap-x-6 gap-y-3">
        <div className="min-w-0">
          <h1 className="font-display text-xl font-bold text-fg">{title}</h1>
          {description && <p className="mt-1 max-w-prose text-sm leading-relaxed text-fg-2">{description}</p>}
        </div>
        {(actions || aside) && (
          // max-w-full: quando quebra para a linha de baixo (celular), um
          // seletor com nome comprido não passa da borda da tela.
          <div className="flex min-w-0 max-w-full flex-shrink-0 items-center gap-2">
            {aside}
            {actions}
          </div>
        )}
      </div>
    </header>
  );
}

/**
 * Seção de conteúdo. O título fica sobre um filete, não dentro de uma caixa.
 * `flush` remove o filete quando a seção já vem depois de outro separador.
 */
export function Section({
  title,
  description,
  actions,
  children,
  flush,
  className,
}: {
  title?: string;
  description?: string;
  actions?: ReactNode;
  children: ReactNode;
  flush?: boolean;
  className?: string;
}) {
  return (
    <section className={clsx(className)}>
      {title && (
        <div
          className={clsx(
            "flex flex-wrap items-baseline justify-between gap-x-4 gap-y-1 pb-3",
            !flush && "border-b border-hairline"
          )}
        >
          <div className="min-w-0">
            <h2 className="font-display text-md font-semibold text-fg">{title}</h2>
            {description && <p className="mt-0.5 text-xs text-fg-3">{description}</p>}
          </div>
          {actions && <div className="flex flex-shrink-0 items-center gap-2">{actions}</div>}
        </div>
      )}
      <div className={title ? "pt-4" : undefined}>{children}</div>
    </section>
  );
}

/** Superfície com borda. Use quando o conteúdo é um objeto, não um agrupamento. */
export function Panel({
  children,
  className,
  tone = "surface",
}: {
  children: ReactNode;
  className?: string;
  tone?: "surface" | "sunken";
}) {
  return (
    <div
      className={clsx(
        "rounded-panel border border-hairline",
        tone === "surface" ? "bg-surface" : "bg-raised",
        className
      )}
    >
      {children}
    </div>
  );
}

/** Título de um bloco dentro de um painel — nome de instrumento, em caixa alta. */
export function PanelLabel({ children, className }: { children: ReactNode; className?: string }) {
  return <p className={clsx("channel-label", className)}>{children}</p>;
}

/**
 * Lista de definição: rótulo à esquerda, valor à direita, filete entre linhas.
 */
export function DataList({ children, className }: { children: ReactNode; className?: string }) {
  return <dl className={clsx("divide-y divide-hairline", className)}>{children}</dl>;
}

export function DataRow({
  label,
  value,
  note,
  tone,
  hint,
  mono,
}: {
  label: string;
  value: ReactNode;
  /** Qualificação em palavras: "folgado", "atenção". */
  note?: string;
  tone?: "ok" | "warn" | "crit";
  hint?: ReactNode;
  /** Identificador técnico longo — reduz o corpo para caber. */
  mono?: boolean;
}) {
  return (
    <div className="flex items-baseline justify-between gap-4 py-2.5">
      <dt className="flex min-w-0 items-center gap-1.5 text-sm text-fg-2">
        <span className="truncate">{label}</span>
        {hint}
      </dt>
      <dd className="flex flex-shrink-0 items-baseline gap-2.5">
        {note && (
          <span
            className={clsx(
              "text-xs",
              tone === "ok" && "text-fg-3",
              tone === "warn" && "text-warn",
              tone === "crit" && "text-crit",
              !tone && "text-fg-3"
            )}
          >
            {note}
          </span>
        )}
        {/* Valor medido: sempre na face da máquina. */}
        <span className={clsx("tnum font-mono text-fg", mono ? "text-micro" : "text-sm")}>{value}</span>
      </dd>
    </div>
  );
}

/** Ponto de status. É o principal portador de cor da interface. */
export function StatusDot({
  tone,
  className,
  label,
}: {
  tone: "ok" | "warn" | "crit" | "idle";
  className?: string;
  /** Texto para leitor de tela quando o ponto aparece sozinho. */
  label?: string;
}) {
  return (
    <span
      role={label ? "img" : undefined}
      aria-label={label}
      aria-hidden={label ? undefined : true}
      className={clsx(
        "inline-block h-1.5 w-1.5 flex-shrink-0 rounded-full",
        tone === "ok" && "bg-ok",
        tone === "warn" && "bg-warn",
        tone === "crit" && "bg-crit",
        tone === "idle" && "bg-fg-3",
        className
      )}
    />
  );
}
