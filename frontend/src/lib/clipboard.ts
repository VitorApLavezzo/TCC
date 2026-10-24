/**
 * Copia texto e diz se deu certo.
 *
 * `navigator.clipboard` só existe em HTTPS ou em localhost — e o próprio
 * painel orienta a abrir pelo IP da rede (http://192.168…), onde ele não
 * existe. Ali o "Copiar" falhava sem dizer nada. O caminho antigo
 * (`execCommand`) ainda funciona nesses casos.
 */
export async function copyText(text: string): Promise<boolean> {
  try {
    if (navigator.clipboard && window.isSecureContext) {
      await navigator.clipboard.writeText(text);
      return true;
    }
  } catch {
    /* tenta o caminho antigo abaixo */
  }
  try {
    const campo = document.createElement("textarea");
    campo.value = text;
    campo.setAttribute("readonly", "");
    campo.style.position = "fixed";
    campo.style.opacity = "0";
    document.body.appendChild(campo);
    campo.select();
    const ok = document.execCommand("copy");
    document.body.removeChild(campo);
    return ok;
  } catch {
    return false;
  }
}

export const COPY_FAILED = ["Não deu para copiar automaticamente.", "Selecione o texto e use Ctrl+C."] as const;
