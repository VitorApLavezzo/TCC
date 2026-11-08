import { useSyncExternalStore } from "react";

/**
 * Se as telas do TCC (Pesquisa, Demonstração, Estudo) aparecem no menu.
 *
 * São ferramentas de quem escreve o trabalho, não de quem monitora um
 * computador: "ablação" e "Isolation Forest" no menu de um leigo só
 * confundem. Ficam escondidas por padrão e se ligam na Conta; a busca do
 * Ctrl+K continua alcançando as três de qualquer jeito.
 */
const STORAGE_KEY = "researchTools";
const listeners = new Set<() => void>();

function read(): boolean {
  try {
    return localStorage.getItem(STORAGE_KEY) === "1";
  } catch {
    return false;
  }
}

export function setResearchTools(enabled: boolean) {
  try {
    localStorage.setItem(STORAGE_KEY, enabled ? "1" : "0");
  } catch {
    /* sem armazenamento: vale só até recarregar */
  }
  listeners.forEach((notify) => notify());
}

function subscribe(notify: () => void) {
  listeners.add(notify);
  return () => {
    listeners.delete(notify);
  };
}

export function useResearchTools(): boolean {
  return useSyncExternalStore(subscribe, read, () => false);
}
