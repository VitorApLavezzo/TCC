/**
 * Copia texto e diz se deu certo. `navigator.clipboard` só existe em HTTPS ou
 * localhost, e o painel é aberto pelo IP da rede (http://192.168…); ali só o
 * caminho antigo (`execCommand`) funciona.
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
    const field = document.createElement("textarea");
    field.value = text;
    field.setAttribute("readonly", "");
    field.style.position = "fixed";
    field.style.opacity = "0";
    document.body.appendChild(field);
    field.select();
    const ok = document.execCommand("copy");
    document.body.removeChild(field);
    return ok;
  } catch {
    return false;
  }
}

export const COPY_FAILED = ["Não deu para copiar automaticamente.", "Selecione o texto e use Ctrl+C."] as const;
