const NO_AI = "análise local (sem IA)";

const DESTINATION_LABELS: Record<string, string> = {
  local: "analisado localmente",
  cloud: "analisado na nuvem",
};

/** O provedor vem antes do destino: numa reescrita por nível, o destino gravado é o da explicação original. */
export function analysisSource(destination?: string, provider?: string): string | null {
  if (provider?.startsWith("claude-cli/")) return "analisado pelo Claude (nuvem)";
  if (provider?.startsWith("ollama/")) return "analisado pelo Ollama (local)";
  if (provider?.startsWith("cloud/")) return DESTINATION_LABELS.cloud;
  if (provider === "análise local") return NO_AI;
  if (destination) return DESTINATION_LABELS[destination] ?? NO_AI;
  return provider ?? null;
}
