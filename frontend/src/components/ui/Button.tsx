import { clsx } from "clsx";
import { ButtonHTMLAttributes, forwardRef, ReactNode } from "react";

type Variant = "primary" | "secondary" | "quiet" | "danger";
type Size = "sm" | "md";

interface Props extends ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: Variant;
  size?: Size;
  icon?: ReactNode;
  loading?: boolean;
  loadingLabel?: string;
}

/**
 * A ação primária usa a cor de marca (accent), reservada a interação e
 * detecção — nunca usada para comunicar "saudável". O estado de saúde
 * continua exclusivamente em ok/warn/crit, nunca no botão.
 */
const VARIANT: Record<Variant, string> = {
  primary: "bg-accent text-canvas font-semibold hover:opacity-90 active:opacity-80",
  secondary: "border border-edge text-fg hover:bg-raised hover:border-fg-3 active:bg-sunken",
  quiet: "text-fg-2 hover:bg-raised hover:text-fg active:bg-sunken",
  danger: "border border-edge text-crit hover:bg-crit/10 hover:border-crit/50 active:bg-crit/15",
};

// Alturas de alvo de toque: 32px e 36px. A escala anterior começava em 28px,
// abaixo do mínimo confortavel para dedo.
const SIZE: Record<Size, string> = {
  sm: "h-8 gap-1.5 px-2.5 text-xs",
  md: "h-9 gap-2 px-3.5 text-sm",
};

export const Button = forwardRef<HTMLButtonElement, Props>(function Button(
  { variant = "secondary", size = "md", icon, loading, loadingLabel, children, className, disabled, ...rest },
  ref
) {
  return (
    <button
      ref={ref}
      type="button"
      disabled={disabled || loading}
      aria-busy={loading || undefined}
      className={clsx(
        "inline-flex items-center justify-center whitespace-nowrap rounded-control transition-all duration-150",
        "disabled:cursor-not-allowed disabled:opacity-45",
        VARIANT[variant],
        SIZE[size],
        className
      )}
      {...rest}
    >
      {icon}
      {loading && loadingLabel ? loadingLabel : children}
    </button>
  );
});

/**
 * Botão só-ícone. `label` é obrigatório e vira aria-label + title — antes
 * esses controles tinham apenas `title` e eram mudos no leitor de tela.
 */
export function IconButton({
  label,
  icon,
  tone = "quiet",
  className,
  ...rest
}: {
  label: string;
  icon: ReactNode;
  tone?: "quiet" | "danger";
} & ButtonHTMLAttributes<HTMLButtonElement>) {
  return (
    <button
      type="button"
      aria-label={label}
      title={label}
      className={clsx(
        "inline-flex h-8 w-8 items-center justify-center rounded-control transition-colors",
        tone === "quiet" && "text-fg-3 hover:bg-raised hover:text-fg",
        tone === "danger" && "text-fg-3 hover:bg-crit/10 hover:text-crit",
        "disabled:cursor-not-allowed disabled:opacity-45",
        className
      )}
      {...rest}
    >
      {icon}
    </button>
  );
}

/** Link textual de ação. Usado no lugar de botões pequenos dentro de seções. */
export function TextButton({
  children,
  className,
  ...rest
}: ButtonHTMLAttributes<HTMLButtonElement>) {
  return (
    <button
      type="button"
      className={clsx("rounded text-xs font-medium text-accent hover:underline", className)}
      {...rest}
    >
      {children}
    </button>
  );
}
