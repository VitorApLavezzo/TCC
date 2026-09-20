# Testes e Resultados

> Texto-base para a monografia. Os números vêm da execução registrada em
> `deteccao-2026-09-19.md` e `deteccao-2026-09-19.csv`, reproduzível pelo
> comando descrito na Seção "Reprodutibilidade".

## 1. Objetivo da avaliação

O sistema proposto faz duas afirmações que precisam ser verificadas
separadamente. A primeira é que ele **detecta** comportamento anômalo em
computadores monitorados. A segunda é que ele **explica** o que detectou em
linguagem acessível a usuários sem formação técnica.

Este capítulo trata da primeira afirmação. A avaliação da qualidade das
explicações, conduzida com um modelo de linguagem atuando como juiz e com
verificação automática dos números citados, é apresentada separadamente.

A escolha de separá-las não é organizacional, e sim metodológica: um sistema
pode escrever explicações excelentes sobre detecções erradas. Medir apenas a
qualidade do texto produziria um resultado favorável e enganoso.

## 2. Metodologia

### 2.1 Por que avaliação baseada em cenários

A avaliação de sistemas de detecção de anomalias enfrenta uma dificuldade
prática: obter dados rotulados. Em um ambiente real, não se sabe com certeza
quais leituras correspondem a um problema e quais correspondem a uso normal, e
provocar incidentes verdadeiros — infectar uma máquina com um minerador de
criptomoeda ou executar um ransomware — é inviável e irresponsável em um
trabalho acadêmico.

A alternativa adotada foi construir um conjunto de cenários com
verdade-fundamental conhecida, divididos em três famílias:

| Família | Verdade-fundamental | Origem dos dados |
|---|---|---|
| Ataque sintético | deve gerar um aviso de tipo específico | leituras fabricadas de forma controlada |
| Normal sintético | não deve gerar aviso algum | programas legítimos com comportamento intenso |
| Normal real | não deve gerar aviso algum | leituras gravadas de uma máquina em uso |

A família **normal sintético** merece destaque porque é onde reside a
contribuição menos óbvia do trabalho. Ela reúne programas legítimos cujo
comportamento é, do ponto de vista puramente estatístico, indistinguível de uma
ameaça: um antivírus executando varredura completa consome processador, lê o
disco intensamente e transfere dados pela rede — exatamente o perfil de um
minerador de criptomoeda exfiltrando resultados. Um sistema que não distingue
os dois casos é inutilizável na prática, porque treina o usuário a ignorar seus
avisos.

A família **normal real** é a mais forte do ponto de vista de validade, pela
razão simples de que a verdade-fundamental não foi escrita por quem está sendo
avaliado. A premissa é direta: durante o período observado o usuário utilizava
o computador normalmente, portanto qualquer aviso emitido naquela janela
constitui um incômodo não solicitado.

### 2.2 Execução pelo caminho real de ingestão

Os cenários não são avaliados contra uma reimplementação simplificada dos
detectores. Cada leitura fabricada atravessa exatamente a mesma função de
processamento (`process_metric`) que recebe as leituras enviadas pelos agentes
instalados nas máquinas monitoradas, acionando os dez detectores
comportamentais, o modelo estatístico, o agrupamento em incidentes e a política
de notificação.

Essa decisão tem custo — a execução completa leva cerca de três minutos, contra
segundos de uma simulação isolada — mas elimina a possibilidade de o benchmark
medir um sistema diferente do que é entregue ao usuário.

### 2.3 Tratamento do período de aprendizado

O sistema implementa um período de aprendizado: enquanto uma máquina não
acumular 100 leituras **e** 6 horas de observação, os detectores que dependem
de histórico permanecem inativos e os avisos gerados não produzem notificação.

Avaliar o sistema sem considerar esse período produziria um resultado
artificialmente favorável, já que uma máquina em aprendizado é silenciosa por
construção. Para evitá-lo, cada cenário é executado em uma máquina efêmera que
recebe previamente uma fase de aquecimento de 110 leituras distribuídas ao
longo de 6,5 horas de tempo virtual — suficiente para concluir o aprendizado e
para que as linhas de base por processo amadureçam, como ocorreria em uso real.

Apenas os avisos gerados após a fase de aquecimento são contabilizados.

Uma alternativa considerada e rejeitada foi marcar as máquinas do benchmark
como sendo de demonstração, o que desativaria o período de aprendizado por
completo. Essa opção mediria um sistema com comportamento diferente do
entregue ao usuário final.

### 2.4 Reprodutibilidade

Duas fontes de não determinismo foram identificadas durante a construção do
benchmark e precisaram ser eliminadas antes que os resultados pudessem ser
considerados válidos.

A primeira é o ruído aleatório aplicado às leituras sintéticas, resolvido com
semente fixa derivada do nome de cada cenário.

A segunda foi menos evidente e mais grave. Os modelos estatísticos treinados
são persistidos em arquivo, identificados pelo número da máquina. Como cada
execução do benchmark cria máquinas efêmeras e as remove ao final, e como a
remoção não apagava o arquivo do modelo, uma execução posterior que reutilizasse
o mesmo número de máquina carregava o modelo treinado na execução anterior. O
efeito era que a mesma entrada produzia saídas diferentes conforme o histórico
de execuções. A correção — descartar o modelo junto com a máquina — também
eliminou um acúmulo indefinido de arquivos em operação normal.

### 2.5 Métricas

Um cenário de ataque é contabilizado como **verdadeiro positivo** quando o tipo
de aviso esperado aparece entre os avisos gerados, e como **falso negativo**
caso contrário. Um cenário normal é contabilizado como **falso positivo** quando
gera qualquer aviso, e como **verdadeiro negativo** quando permanece silencioso.

A partir da matriz de confusão derivam-se:

- **Precisão** = VP / (VP + FP) — dos avisos emitidos, quantos correspondiam a
  um problema real;
- **Revocação** = VP / (VP + FN) — dos problemas existentes, quantos foram
  encontrados;
- **F1** = média harmônica entre precisão e revocação;
- **Taxa de alarme falso** = FP / (FP + VN) — das situações normais, quantas
  geraram aviso.

Quando o denominador de uma razão é zero, a métrica é reportada como
indefinida, e não como zero. A distinção importa: em um conjunto sem nenhum
cenário de ataque, uma revocação de 0% seria lida como "o sistema não detectou
nada", afirmação diferente e falsa.

## 3. Resultados

A execução compreendeu 14 cenários e durou 173 segundos.

### 3.1 Matriz de confusão

| | Sistema emitiu aviso | Sistema permaneceu silencioso |
|---|---|---|
| **Havia problema** | 6 | 2 |
| **Não havia problema** | 3 | 3 |

### 3.2 Métricas agregadas

| Métrica | Valor |
|---|---|
| Precisão | 66,7% |
| Revocação | 75,0% |
| F1 | 70,6% |
| Taxa de alarme falso | 50,0% |

### 3.3 Resultado por cenário

| Cenário | Família | Esperado | Detectado | Veredito |
|---|---|---|---|---|
| Minerador de criptomoeda | ataque | `suspicious_process` | `suspicious_process`, `malware_pattern`, `cpu_loop` | acerto |
| Executável sem assinatura na pasta Temp | ataque | `malware_pattern` | `malware_pattern`, `unknown_process` | acerto |
| Programa travado no processador | ataque | `cpu_loop` | `unknown_process`, `cpu_loop` | acerto |
| Vazamento de memória | ataque | `memory_leak` | `memory_leak` | acerto |
| Sequestro de dados (ransomware) | ataque | `ransomware_canary` | `malware_pattern`, `ransomware_canary`, `unknown_process` | acerto |
| Vírus disfarçado de `svchost.exe` | ataque | `process_masquerading` | `process_masquerading`, `malware_pattern` | acerto |
| Disco enchendo rapidamente | ataque | `disk_forecast` | `disk_space_change` | falha |
| Programa contatando servidor em intervalos | ataque | `beaconing` | — | falha |
| Antivírus em varredura completa | normal sintético | nenhum | — | acerto |
| Backup em nuvem | normal sintético | nenhum | — | acerto |
| Atualização do sistema operacional | normal sintético | nenhum | — | acerto |
| Jogo exigente em tela cheia | normal sintético | nenhum | `cpu_loop` | alarme falso |
| Compilação usando todos os núcleos | normal sintético | nenhum | `high_cpu`, `cpu_loop` | alarme falso |
| Uso real (490 leituras, Linux Mint 22.3) | normal real | nenhum | 7 tipos distintos | alarme falso |

## 4. Análise

### 4.1 Detecção de ameaças

Seis dos oito cenários de ataque foram detectados com o tipo de aviso esperado.
Os acertos cobrem as categorias mais relevantes do ponto de vista de segurança:
mineração de criptomoeda, execução a partir de diretório temporário,
ransomware, processo disfarçado de binário do sistema e vazamento de memória.

Observa-se que vários cenários produziram mais de um tipo de aviso. Esse
comportamento é intencional: o sistema agrupa sinais simultâneos em um
incidente único, apresentando ao usuário o aviso mais grave e mantendo os
demais como cadeia de causa.

### 4.2 Falsos negativos

O cenário de **disco enchendo rapidamente** gerou `disk_space_change` em vez do
esperado `disk_forecast`. Trata-se de uma falha de classificação, não de
detecção: o sistema percebeu a anomalia e alertou o usuário, apenas sob outro
rótulo. O critério de avaliação adotado exige correspondência exata do tipo, o
que é conservador e foi mantido para evitar flexibilizações convenientes.

O cenário de **beaconing** não produziu aviso algum. Esta é uma falha de
detecção genuína e constitui a limitação mais relevante identificada, dado que
comunicação periódica com servidor externo é indicador clássico de
comprometimento.

### 4.3 Falsos positivos

Os três alarmes falsos compartilham uma causa comum: **carga legítima intensa e
sustentada**.

O **jogo em tela cheia** e a **compilação de projeto** foram classificados como
`cpu_loop`, detector destinado a identificar processos travados em laço
infinito. Um jogo mantendo 88% de utilização do processador não está travado —
está funcionando como projetado. O detector não distingue utilização intensa
legítima de utilização intensa patológica.

O cenário de **uso real** gerou sete tipos distintos de aviso ao longo de 490
leituras.

É relevante registrar que o cenário de **antivírus em varredura completa**
figura entre os acertos. Esse caso motivou a implementação de uma camada de
confiança baseada em assinatura digital, diretório de instalação e reputação do
executável entre máquinas — sinais que o agente já coletava, mas que eram
utilizados apenas como evidência contra o programa, nunca a seu favor. Antes
dessa camada, uma varredura de antivírus era classificada como padrão de
comportamento malicioso.

## 5. Limitações e ameaças à validade

**Cenários de ataque são sintéticos.** Não medem capacidade de detecção contra
malware real nem contra técnicas de evasão. Um atacante ciente dos detectores
implementados pode contorná-los de maneiras que este conjunto não captura.

**A verdade-fundamental dos cenários sintéticos foi definida pelo autor do
sistema.** Há risco de os cenários refletirem, ainda que involuntariamente,
aquilo que o sistema já sabe detectar.

**A amostra de uso real provém de uma única máquina e de um único perfil de
uso.** Não permite generalização para outros ambientes, sistemas operacionais
ou padrões de utilização.

**O critério de avaliação do cenário real é excessivamente rigoroso.**
Contabilizar qualquer aviso emitido em 490 leituras como um único falso
positivo trata de forma idêntica um sistema que emite um aviso por dia e outro
que emite cem. Para dados reais, a métrica adequada seria avisos por hora, e
não um indicador binário. A taxa de alarme falso de 50% reportada deve ser
interpretada à luz dessa limitação.

**O conjunto é pequeno.** Quatorze cenários produzem métricas com intervalos de
confiança largos; cada cenário individual desloca as métricas agregadas em
vários pontos percentuais.

## 6. Reprodutibilidade

A avaliação completa é reproduzível por terceiros com o comando:

```
docker compose exec -T backend python -m app.benchmark --user <id> --real <id_da_máquina> > relatorio.md
```

O parâmetro `--csv` produz o mesmo conteúdo em formato tabular. A execução é
determinística: repetições sucessivas produzem resultados idênticos.

## 7. Trabalhos futuros

Os resultados apontam três direções imediatas, em ordem de impacto:

1. **Estender a camada de confiança aos detectores de desempenho.** Os dois
   alarmes falsos sintéticos decorrem de detectores que ainda não consultam a
   identidade do executável responsável, ao contrário dos detectores de
   segurança.

2. **Investigar a falha de detecção de beaconing.** Falso negativo em categoria
   relevante de ameaça.

3. **Substituir o critério binário do cenário real por taxa de avisos por
   hora**, tornando a medição de falsos positivos em dados reais proporcional à
   duração da observação.
