# Benchmark de detecção — resultados mensuráveis para a monografia

**Data:** 19/09/2026

## Problema

A afirmação central do projeto é "detecta anomalias em computadores". Não existe
número que a sustente. O que existe é avaliação da **explicação**
(`evaluation.py`: IA-juíza, comparação de provedores, precisão factual) — a
qualidade do texto que descreve o problema, não a qualidade de encontrar o
problema.

Os dados reais disponíveis são insuficientes para um capítulo de resultados:
1 máquina, 1.037 leituras, 5 anomalias, 2 com feedback, 0 avaliadas. O caminho
é benchmark reprodutível, não estatística de uso.

## Método

Cenários com gabarito passando pelo **mesmo** `process_metric` da coleta real —
não uma simulação paralela. Três famílias:

| Família | Gabarito | Origem |
|---|---|---|
| Ataque sintético | deve gerar o aviso X | cenários controlados |
| Normal sintético | não deve gerar aviso | programas legítimos que parecem problema |
| Normal real | não deve gerar aviso | leituras já gravadas de uma máquina em uso |

Ataque sintético é inevitável e é prática aceita: não se infecta uma máquina de
verdade num TCC. O lado que mais importa para a crítica — falso positivo — é
medido também em dado real, onde o gabarito não foi escrito por quem é avaliado.

### Período de aprendizado

Cada cenário roda numa máquina efêmera que recebe antes uma fase de
aquecimento: leituras com carimbo de tempo virtual espalhadas por mais de 6
horas, suficientes para a máquina sair do período de aprendizado e para os
baselines de processo amadurecerem.

Alternativa rejeitada: marcar a máquina como `is_demo` para desligar o portão
do aprendizado. Mediria um sistema diferente do que o usuário recebe.

### Métricas

Matriz de confusão e, dela, precisão, revocação, F1 e taxa de falso positivo.
Um cenário de ataque conta como verdadeiro positivo quando o tipo esperado
aparece entre os avisos gerados; como falso negativo quando não aparece. Um
cenário normal conta como falso positivo quando gera qualquer aviso.

Além dos agregados, uma linha por cenário com esperado, obtido e veredito — é
a tabela que responde "e nos casos em que erra?".

## Arquitetura

`app/services/benchmark.py` executa; o comando de terminal e o endpoint do
painel chamam a mesma função, então nunca divergem.

- **Comando:** `python -m app.benchmark` imprime Markdown na saída padrão
  (`--csv` para CSV). Redirecionamento resolve o destino, sem caminho
  configurável nem dependência de qual pasta está montada no contêiner.
- **Endpoint:** dispara em segundo plano (são ~15 cenários com aquecimento;
  longe demais para requisição síncrona) e grava em `benchmark_runs`.
- **Painel:** seção na página Pesquisa com a última execução e botão de baixar.

Isolamento: máquinas efêmeras removidas por `delete_machine_cascade` ao fim de
cada cenário, inclusive em caso de erro.

## Antes e depois

Medição única, feita fora do código: o mesmo benchmark roda num worktree do
commit anterior às correções de falso positivo, e as duas colunas entram no
relatório com nota dizendo qual commit é cada uma.

Alternativa rejeitada: um "modo legado" permanente que desliga a camada de
confiança. É dívida permanente no código de produção para gerar um gráfico.

## Limitações a declarar na monografia

- Cenários de ataque são sintéticos; não medem evasão real nem malware real.
- O gabarito dos sintéticos foi escrito pelo autor do sistema.
- A amostra de normal real vem de uma única máquina e de um único perfil de uso.
