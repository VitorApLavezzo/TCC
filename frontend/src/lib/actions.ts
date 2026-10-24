/**
 * O que cada ação remota faz de fato, para a confirmação não prometer mais
 * do que o sistema entrega.
 */
const CONSEQUENCIA: Record<string, string> = {
  kill_process: "O programa fecha na hora, e o que estiver aberto nele sem salvar se perde.",
  clean_temp: "Os arquivos temporários são apagados e não voltam. Programas abertos podem precisar ser reabertos.",
  isolate_network:
    "O computador fica sem internet e sem rede até você clicar em “Restaurar a rede” neste mesmo aviso.",
};

export function confirmBody(command: string, machineName?: string | null) {
  const onde = machineName ? `em ${machineName}` : "no computador";
  const consequencia = CONSEQUENCIA[command] ?? "";
  return `Esta ação será executada ${onde}. ${consequencia}`.trim();
}
