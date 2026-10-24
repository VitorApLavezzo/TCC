/**
 * Se a pessoa pediu ao sistema operacional menos movimento. O CSS global já
 * respeita isso; os gráficos animam por JavaScript e precisam perguntar.
 */
export function prefersReducedMotion(): boolean {
  try {
    return window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  } catch {
    return false;
  }
}
