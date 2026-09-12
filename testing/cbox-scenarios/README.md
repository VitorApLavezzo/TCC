# Harness de validação com fault injection (cbox)

Suíte de teste para validar, de forma reproduzível, que o AnomalyDetect
detecta corretamente cada tipo de anomalia comportamental — subindo uma
máquina Linux descartável (via [`cbox`](https://github.com/Rynaro/cardboard-box)
+ `distrobox`) com um problema específico já injetado, instalando o agente
nela e conferindo na API real se a anomalia esperada aparece.

## Por quê

Testar manualmente "detectou uma vez" não prova muito. Este harness permite
perguntas mais fortes para o TCC:
- **Detecta de forma consistente?** Rode o mesmo cenário N vezes (`REPEATS=5`)
  e meça a taxa de acerto.
- **Detecta pela razão certa?** Cada cenário injeta *exatamente* o problema
  que um detector específico (`behavior_analyzer.py`) foi desenhado para
  identificar — não é só "deixa o computador com uso alto de recursos".
- **É reproduzível entre execuções independentes?** Cada ciclo cadastra uma
  **máquina nova** no painel (evita o cooldown de 30 min e a baseline
  acumulada de execuções anteriores — ver observações abaixo).

## Pré-requisitos

No host que vai rodar os testes:
- [`cbox`](https://github.com/Rynaro/cardboard-box) instalado (`make install`
  a partir do repositório do projeto)
- `distrobox >= 1.6` e um backend (`podman` ou `docker`)
- `curl`, `python3` (para falar com a API do AnomalyDetect)
- O AnomalyDetect rodando e acessível (`docker compose up -d` no diretório
  raiz deste projeto)

## Como rodar

```bash
cd testing/cbox-scenarios

# o único cenário validado até agora
./run_scenarios.sh cpu_loop

# repetições, para medir consistência (já testado: 3/3 detecções, sempre
# em ~25s, sempre severidade "high")
REPEATS=5 ./run_scenarios.sh cpu_loop

# apontando para outro servidor
SERVER=http://192.168.0.10:8000 ./run_scenarios.sh cpu_loop
```

O script cria uma conta de teste dedicada (`cbox_harness` por padrão — troque
com `USERNAME=`/`PASSWORD=`) e usa códigos de pareamento de uso único, um por
execução — assim cada tentativa é uma máquina nova de verdade, sem estado
acumulado de tentativas anteriores.

Ao final imprime uma tabela: cenário, tentativa, resultado, tempo até
detectar e a anomalia encontrada.

## Cenários incluídos

| Cenário | Boxfile | O que injeta | Detector alvo | Status |
|---|---|---|---|---|
| `cpu_loop` | `cpu_loop.Boxfile.toml` | Loop infinito de CPU (`while True: pass`) | `detect_cpu_loop` | ✅ Validado (3/3, sempre `high`) |

> **Mudança de prazo:** a validação original detectava em ~25 s. Os detectores
> passaram a exigir uma **janela mínima de tempo**, não apenas um número de
> coletas — com `COLLECTION_INTERVAL=5`, "3 de 5 coletas" eram 25 s de pico, o
> que confundia um programa abrindo com um programa travado. `detect_cpu_loop`
> agora quer ≥ 60 s de CPU dominante sustentada, então a espera do harness subiu
> de 60 s para 180 s. É uma troca deliberada: menos alarme falso, detecção mais
> lenta.

### Alternativa sem containers: o modo demonstração do painel

Desde a versão 2 dá para injetar os mesmos tipos de anomalia direto pelo painel
(**Demonstração**), sem `cbox`, `distrobox` nem Linux: o backend gera leituras
sintéticas que passam pelo **mesmo** caminho das reais (detectores, modelo, IA,
incidentes). Serve para apresentar à banca; este harness continua sendo o teste
mais forte, porque o problema é injetado num sistema operacional de verdade e o
agente real coleta do sistema real.

Cada Boxfile tem, nos comentários, o raciocínio exato de timing (quantas
coletas cada detector exige antes de conseguir avaliar algo).

### Cenários em progresso (branch `feat/cbox-more-scenarios`)

Os outros 4 detectores comportamentais têm Boxfiles escritos e sintaxe
validada (TOML + Python), mas ainda **não foram executados de ponta a ponta**
contra o `cbox` real — ficaram numa branch separada para terminar de validar:

| Cenário | O que injeta | Detector alvo |
|---|---|---|
| `memory_leak` | Alocação contínua de memória, nunca liberada | `detect_memory_leak` |
| `ddos_indicator` | ~300 conexões TCP abertas de repente após baseline calma | `detect_ddos_indicators` |
| `suspicious_process` | Processo com nome de ameaça conhecida (`xmrig`) | `detect_new_suspicious_process` |
| `behavioral_change` | CPU + memória + rede subindo juntos após período ocioso | `detect_behavioral_change` |

### Cenários deliberadamente fora desta suíte (por enquanto)

- **`resource_abuse`** — exige que o processo já seja "conhecido" pela
  baseline (visto normalmente por um tempo) e *depois* dispare bem acima do
  seu próprio histórico. Dá para simular, mas precisa de um Boxfile em duas
  fases mais longo (aquecer a baseline, depois disparar) — não incluído
  ainda para manter o primeiro lote simples e confiável.
- **`malware_pattern`** — exige uma combinação de indicadores (rodar de
  pasta temporária, sem linha de comando visível, etc.) mais difícil de
  fabricar de forma limpa via `distrobox enter`. Interessante notar: ele
  **já apareceu sozinho** durante a validação do cenário `cpu_loop` (ver
  abaixo) — então já está indiretamente coberto.

## Importante: os Boxfiles usam `isolated = true`

Por padrão, o `distrobox` compartilha o `$HOME` real do host com o container
(é assim que ele integra o box ao seu sistema). Sem isolamento, os scripts de
falha injetada e o agente instalado durante os testes escreveriam direto na
sua pasta pessoal de verdade (`~/.anomalydetect`) — e, pior, o processo do
"problema" injetado (loop de CPU, vazamento de memória) ficaria visível na
lista de processos real do seu computador, já que o namespace de PID também
é compartilhado por padrão.

Por isso todos os Boxfiles desta suíte declaram `[box] isolated = true`, que
dá ao container um `$HOME` privado e isolamento de processo/IPC — os testes
ficam contidos, sem tocar no seu sistema real nem em uma eventual instalação
de produção do agente no mesmo host.

## O que foi validado nesta sessão

O cenário `cpu_loop` foi validado de ponta a ponta, com o `cbox` real
instalado (build a partir do código-fonte, via `make install`) e `distrobox`
+ `podman` como backend:

- **3 execuções independentes, 3 detecções corretas** — sempre
  `cpu_loop:high`, sempre em ~25s. Máquina nova a cada ciclo (sem
  reaproveitar cadastro), confirmando que a detecção é determinística e
  não depende de sorte ou de estado acumulado.
- **Bugs reais encontrados e corrigidos no processo** (nenhum estava
  presente antes de eu tentar rodar isto de verdade — só apareceram testando
  contra o sistema real):
  1. `install.sh` usava `set -e` e travava silenciosamente em imagens sem
     `crontab` (comum em containers/servidores minimalistas) — corrigido
     para pular essa etapa graciosamente.
  2. `install.sh` não tinha fallback para sistemas sem `pip`/`venv`
     pré-instalados (ex: Ubuntu Server puro) — agora tenta `ensurepip` e,
     se ainda assim falhar, mostra uma mensagem clara em vez de um erro
     críptico.
  3. Os Boxfiles usavam nome de imagem curto (`fedora-toolbox:latest`), que
     falha em hosts Podman sem registro padrão configurado — corrigido para
     nome totalmente qualificado.
  4. Os scripts de injeção de falha usavam `disown`, que não existe no
     `sh` (usado pelo `distrobox enter` para rodar os passos de
     provisionamento) — removido.
  5. `run_scenarios.sh` não isolava o `$HOME` dos containers de teste,
     então os testes escreviam na pasta pessoal real do host — corrigido
     com `[box] isolated = true`.
  6. `run_scenarios.sh` misturava mensagens de progresso com o canal de
     retorno da função (capturado via `$(...)`), deixando a execução
     silenciosa e quebrando o parse do resultado — corrigido enviando logs
     para stderr.
  7. O agente era instalado sem fixar `COLLECTION_INTERVAL`, então usava o
     padrão de 10s em vez dos 5s que todos os prazos do harness assumiam —
     corrigido explicitamente na instalação.
- Achado extra (não é bug): `malware_pattern` disparou junto com
  `cpu_loop` num teste isolado anterior (fora deste harness) porque o
  processo de teste rodava como `root`, e "processo privilegiado com CPU
  alta" é um dos indicadores desse detector. Comportamento correto do
  sistema, vale citar no capítulo de resultados como tal.

Essa lista longa de bugs — todos encontrados só ao rodar contra o sistema
real, nenhum visível por inspeção de código — é em si um argumento a favor
de manter esse tipo de teste no fluxo de trabalho.

## Sobre repetibilidade (subir, derrubar, subir de novo)

Se você quiser validar manualmente (fora deste script) que o sistema
detecta a mesma coisa em execuções repetidas, dois cuidados importantes:

1. **Cadastre uma máquina nova a cada ciclo** (o que este script já faz
   automaticamente). Reaproveitar a mesma máquina faz o cooldown de 30 min
   (`ANOMALY_COOLDOWN_MINUTES` em `anomaly_service.py`) mascarar a segunda
   detecção — pareceria "não detectou de novo" quando na verdade é o
   comportamento correto do sistema evitando alertas duplicados.
2. **Espere o mesmo tempo nas duas execuções** — os detectores exigem um
   número mínimo de coletas de histórico (5 a 16, dependendo do detector)
   antes de conseguirem avaliar qualquer coisa.
