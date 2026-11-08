import { RotateCw } from "lucide-react";
import { Panel } from "./Layout";
import { Button } from "./Button";

/**
 * Uma seção que não conseguiu carregar: diz o que não veio e oferece tentar de
 * novo, em vez de sumir e parecer que não há nada ali.
 */
export function LoadError({
  what,
  onRetry,
  compact,
}: {
  /** O que não carregou, em palavras: "a saúde das peças". */
  what: string;
  onRetry?: () => void;
  compact?: boolean;
}) {
  const content = (
    <div className="flex flex-wrap items-center justify-between gap-3">
      <p className="text-sm text-fg-2">
        Não foi possível carregar {what}.{" "}
        <span className="text-fg-3">O resto da tela continua válido.</span>
      </p>
      {onRetry && (
        <Button size="sm" variant="secondary" onClick={onRetry} icon={<RotateCw size={13} aria-hidden="true" />}>
          Tentar de novo
        </Button>
      )}
    </div>
  );
  return compact ? content : <Panel className="p-4">{content}</Panel>;
}
