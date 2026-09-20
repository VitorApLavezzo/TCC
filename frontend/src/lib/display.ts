/**
 * Preferências de leitura: densidade e tamanho da letra.
 *
 * O público declarado do sistema é gente que não é da área — e boa parte
 * dela enxerga mal de perto. A interface é compacta de propósito (muita
 * medida por tela), o que é ótimo para quem monitora doze máquinas e ruim
 * para quem tem uma e precisa ler. As duas opções ficam no atributo do
 * documento, e o CSS faz o resto: nenhum componente precisa saber disso.
 */
export type Density = "confortavel" | "compacta";
export type FontScale = "normal" | "grande" | "maior";

const PADRAO = { density: "compacta" as Density, scale: "normal" as FontScale };

function ler<T extends string>(chave: string, padrao: T): T {
  try {
    return (localStorage.getItem(chave) as T) || padrao;
  } catch {
    return padrao;
  }
}

export function getDisplay(): { density: Density; scale: FontScale } {
  return {
    density: ler("density", PADRAO.density),
    scale: ler("fontScale", PADRAO.scale),
  };
}

export function applyDisplay(prefs: { density?: Density; scale?: FontScale } = {}): void {
  const atual = getDisplay();
  const density = prefs.density ?? atual.density;
  const scale = prefs.scale ?? atual.scale;
  try {
    localStorage.setItem("density", density);
    localStorage.setItem("fontScale", scale);
  } catch {
    /* sem armazenamento: vale só nesta sessão */
  }
  document.documentElement.dataset.density = density;
  document.documentElement.dataset.scale = scale;
}
