/**
 * Glossário: todo termo técnico que aparece na tela tem uma frase aqui.
 *
 * Regra: explique o que a pessoa ganha em saber, não o que o sistema faz
 * por dentro. "Isolation Forest" não precisa de definição — precisa dizer
 * se o número é bom ou ruim.
 */

export const GLOSSARY: Record<string, string> = {
  cpu: "O processador é o que faz as contas do computador. Acima de 80% por muito tempo, tudo começa a ficar lento.",
  memoria:
    "Memória RAM é onde ficam os programas abertos. Quando enche, o computador passa a usar o disco como memória e fica muito mais lento.",
  disco:
    "Espaço de armazenamento usado. Passando de 90%, o computador pode travar ao salvar arquivos ou atualizar programas.",
  swap:
    "Espaço do disco emprestado quando a memória RAM acaba. Usar swap é normal em pouca quantidade; muito swap é sinal de que falta memória.",
  temperatura:
    "Temperatura do processador. Acima de 88 °C ele se autolimita para não queimar, e o computador fica lento. Costuma ser poeira no ventilador.",
  load:
    "Quantidade média de tarefas na fila do processador. Comparamos com o número de núcleos da sua máquina: mais tarefas do que núcleos significa fila de espera.",
  uptime: "Tempo desde a última vez que o computador foi ligado.",
  processos: "Quantos programas e serviços estão rodando neste momento, contando os invisíveis do sistema.",
  conexoes:
    "Conexões de rede abertas agora. Um salto repentino pode indicar download em massa, atualização — ou algo indesejado enviando dados.",
  rede: "Velocidade de dados entrando e saindo pela internet neste instante.",
  gpu: "A placa de vídeo. Fica ocupada em jogos, edição de vídeo e algumas tarefas de IA.",
  vram: "Memória própria da placa de vídeo. Quando enche, jogos e programas gráficos travam.",
  bateria: "Carga atual da bateria.",
  saude_bateria:
    "Quanto a bateria ainda segura em relação à capacidade de quando era nova. Abaixo de 80% ela dura visivelmente menos.",
  ciclos:
    "Quantas vezes a bateria foi carregada por completo. Baterias de notebook costumam durar entre 300 e 1000 ciclos.",
  particoes: "As divisões do seu disco. Cada uma enche de forma independente.",
  score:
    "O quanto esta leitura fugiu do comportamento habitual desta máquina, medido pelo modelo estatístico. Quanto mais negativo, mais fora do padrão.",
  aprendizado:
    "O sistema aprende o que é normal em cada computador antes de apontar desvios. Até terminar, ele só usa as regras fixas de detecção.",
  ao_vivo:
    "O computador está enviando leituras neste momento, a cada 30 segundos, por conexão direta com o servidor.",
  agent_token:
    "A senha que identifica este computador ao enviar dados. Quem tiver o token pode enviar leituras em nome desta máquina — trate como senha.",
  chave_massa:
    "Uma chave reutilizável para instalar em muitos computadores de uma vez, sem digitar código em cada um.",
  codigo_pareamento:
    "Um código de uso único, válido por pouco tempo, que autoriza um computador novo a se registrar na sua conta.",
  frequencia_leitura:
    "De quanto em quanto tempo o agente manda uma nova leitura. Automática deixa o servidor decidir (mais rápido quando algo foge do normal, mais devagar quando está tudo calmo).",
  tempo_real:
    "Força leituras a cada 5 segundos por um tempo limitado, para acompanhar de perto um problema acontecendo agora. Volta sozinho à frequência escolhida quando o tempo acaba.",
};

/** Como cada anomalia se explica em uma frase, antes da IA responder. */
export const ANOMALY_TYPE_HINTS: Record<string, string> = {
  high_cpu: "O processador ficou perto do limite por tempo suficiente para deixar o computador lento.",
  high_memory: "A memória RAM encheu. Programas passam a fechar sozinhos ou travar.",
  resource_exhaustion: "Processador e memória saturaram juntos — o computador fica quase inutilizável.",
  disk_full: "O disco está perto de encher. Salvar arquivos e atualizar programas pode falhar.",
  network_spike: "O tráfego de internet saltou muito acima do normal desta máquina.",
  memory_leak: "Um programa vem acumulando memória sem devolver — é um defeito dele, não seu.",
  cpu_loop: "Um programa travou num laço e está consumindo processador sem fazer nada útil.",
  ddos_indicator: "Muitas conexões de rede abertas de uma vez, num padrão de ataque ou de abuso.",
  unknown_process: "Apareceu um programa que nunca havia rodado aqui, e ele está consumindo recursos.",
  suspicious_process: "Um programa com nome conhecido de ameaça está rodando nesta máquina.",
  malware_pattern: "A combinação de sinais bate com o comportamento típico de vírus.",
  resource_abuse: "Um programa conhecido está gastando muito mais do que ele mesmo costuma gastar.",
  behavioral_change: "Várias métricas mudaram de padrão ao mesmo tempo, sem causa aparente.",
  behavioral_anomaly: "A leitura fugiu do padrão que o sistema aprendeu para esta máquina.",
  unknown: "O sistema detectou um desvio, mas não conseguiu classificá-lo.",
};

/** Frase única de urgência por severidade, na voz da interface. */
export const SEVERITY_URGENCY: Record<string, string> = {
  critical: "Aja agora: isto pode travar o computador ou indicar uma ameaça séria.",
  high: "Resolva hoje: o computador pode ficar lento ou instável se nada for feito.",
  medium: "Investigue quando puder: não é urgente, mas não deve ser ignorado.",
  low: "Só para você saber: nenhuma ação é necessária.",
};
