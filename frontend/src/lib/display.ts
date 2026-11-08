/**
 * Preferências de leitura (densidade e tamanho da letra): a interface é
 * compacta de propósito, e boa parte do público enxerga mal de perto. Ficam
 * no atributo do documento e o CSS faz o resto.
 */
export type Density = "confortavel" | "compacta";
export type FontScale = "normal" | "grande" | "maior";

const DEFAULTS = { density: "compacta" as Density, scale: "normal" as FontScale };

function read<T extends string>(key: string, fallback: T): T {
  try {
    return (localStorage.getItem(key) as T) || fallback;
  } catch {
    return fallback;
  }
}

export function getDisplay(): { density: Density; scale: FontScale } {
  return {
    density: read("density", DEFAULTS.density),
    scale: read("fontScale", DEFAULTS.scale),
  };
}

export function applyDisplay(prefs: { density?: Density; scale?: FontScale } = {}): void {
  const current = getDisplay();
  const density = prefs.density ?? current.density;
  const scale = prefs.scale ?? current.scale;
  try {
    localStorage.setItem("density", density);
    localStorage.setItem("fontScale", scale);
  } catch {
    /* sem armazenamento: vale só nesta sessão */
  }
  document.documentElement.dataset.density = density;
  document.documentElement.dataset.scale = scale;
}
