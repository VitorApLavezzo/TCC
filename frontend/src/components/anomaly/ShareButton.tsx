import { useState } from "react";
import { copyText, COPY_FAILED } from "../../lib/clipboard";
import { shareApi, errorMessage } from "../../services/api";
import { Button, TextButton } from "../ui/Button";
import { useToast } from "../ui/Toast";

/** Link temporário, somente leitura, com tudo do incidente, para mandar ao técnico sem que ele precise de conta. */
export function ShareButton({ anomalyId }: { anomalyId: number }) {
  const toast = useToast();
  const [link, setLink] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const create = async () => {
    setBusy(true);
    try {
      const res = await shareApi.create(anomalyId, 72);
      const url = res.data.url ?? `${window.location.origin}/compartilhado/${res.data.token}`;
      setLink(url);
      toast.success(
        (await copyText(url))
          ? "Link copiado. Válido por 72 horas, somente leitura."
          : "Link criado. Válido por 72 horas, somente leitura."
      );
    } catch (err) {
      toast.error(errorMessage(err));
    } finally {
      setBusy(false);
    }
  };

  if (link) {
    return (
      <div className="flex flex-wrap items-center gap-2">
        <input
          readOnly
          aria-label="Link para o técnico"
          value={link}
          onFocus={(e) => e.currentTarget.select()}
          className="min-w-0 flex-1 rounded-control border border-edge bg-sunken px-2.5 py-1.5 font-mono text-micro text-fg-2"
        />
        <TextButton
          onClick={async () => ((await copyText(link)) ? toast.success("Copiado.") : toast.error(...COPY_FAILED))}
        >
          Copiar
        </TextButton>
      </div>
    );
  }

  return (
    <Button size="sm" variant="quiet" loading={busy} onClick={create}>
      Gerar link para o técnico
    </Button>
  );
}
