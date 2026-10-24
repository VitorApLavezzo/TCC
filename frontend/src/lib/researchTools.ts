import { useSyncExternalStore } from "react";

/**
 * Se as telas do TCC (Pesquisa, Demonstração, Estudo) aparecem no menu.
 *
 * São ferramentas de quem escreve o trabalho, não de quem monitora um
 * computador: "ablação" e "Isolation Forest" no menu de um leigo só
 * confundem. Ficam escondidas por padrão e se ligam na Conta; a busca do
 * Ctrl+K continua alcançando as três de qualquer jeito.
 */
const CHAVE = "researchTools";
const ouvintes = new Set<() => void>();

function ler(): boolean {
  try {
    return localStorage.getItem(CHAVE) === "1";
  } catch {
    return false;
  }
}

export function setResearchTools(ligado: boolean) {
  try {
    localStorage.setItem(CHAVE, ligado ? "1" : "0");
  } catch {
    /* sem armazenamento: vale só até recarregar */
  }
  ouvintes.forEach((avisar) => avisar());
}

function assinar(avisar: () => void) {
  ouvintes.add(avisar);
  return () => {
    ouvintes.delete(avisar);
  };
}

export function useResearchTools(): boolean {
  return useSyncExternalStore(assinar, ler, () => false);
}
