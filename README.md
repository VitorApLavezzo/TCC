# AnomalyDetect

**Sistema inteligente de monitoramento e detecção de anomalias em computadores, com explicações geradas por Inteligência Artificial em linguagem simples.**

Projeto de TCC — o objetivo é que **qualquer pessoa**, mesmo sem conhecimento técnico, consiga monitorar seus computadores e **entender** o que está acontecendo quando algo sai do normal: o sistema não só detecta o problema, como explica a causa provável e diz o que fazer, passo a passo.

---

## Índice

- [Como funciona (visão geral)](#como-funciona-visão-geral)
- [Detecção de anomalias](#detecção-de-anomalias)
- [Explicações por IA](#explicações-por-ia)
- [Tecnologias](#tecnologias)
- [Estrutura do projeto](#estrutura-do-projeto)
- [Como rodar o sistema](#como-rodar-o-sistema)
- [Conectando computadores (agente)](#conectando-computadores-agente)
- [Gerenciando as máquinas](#gerenciando-as-máquinas)
- [Configuração (.env)](#configuração-env)
- [Configurando a IA (Ollama e Claude)](#configurando-a-ia-ollama-e-claude)
- [Login com Google (opcional)](#login-com-google-opcional)
- [Principais endpoints da API](#principais-endpoints-da-api)
- [Operação: observabilidade, CI, backup e segurança](#operação-observabilidade-ci-backup-e-segurança)
- [Testes](#testes)
- [Solução de problemas](#solução-de-problemas)

---

## Como funciona (visão geral)

O sistema tem três partes que conversam entre si:

```
┌─────────────────┐   métricas a cada 30s   ┌──────────────────────────┐
│     AGENTE      │ ──────────────────────► │         BACKEND          │
│ (roda em cada   │    (HTTP + token)       │  FastAPI + PostgreSQL    │
│  computador     │                         │                          │
│  monitorado)    │                         │  1. Grava as métricas    │
└─────────────────┘                         │  2. Detecta anomalias    │
                                            │     (heurísticas + ML)   │
┌─────────────────┐    tempo real (WS)      │  3. Gera explicação IA   │
│    FRONTEND     │ ◄─────────────────────► │     (Ollama → Groq →     │
│  React + Vite   │       REST (HTTP)       │      análise local)      │
│  (painel web)   │                         └──────────────────────────┘
└─────────────────┘
```

1. **Agente** (`agent/`) — um programa Python leve que roda em cada computador monitorado. A cada intervalo (padrão 30 s) ele coleta CPU, memória, disco, rede, GPU, temperatura, bateria e os processos que mais consomem recursos, e envia tudo ao backend. Tem ícone na bandeja do sistema (com opções "Abrir painel" e "Sair") e inicia junto com o sistema operacional.

2. **Backend** (`backend/`) — API em FastAPI que recebe as métricas, roda a detecção de anomalias em duas camadas (ver abaixo), treina um modelo de Machine Learning **por máquina** e gera explicações via LLM. Transmite atualizações em tempo real por WebSocket.

3. **Frontend** (`frontend/`) — painel web em React onde o usuário cria a conta, conecta computadores (com instalador de 2 cliques), acompanha o dashboard em tempo real e lê as anomalias com as explicações da IA.

---

## Detecção de anomalias

A detecção acontece **a cada coleta recebida**, em duas camadas complementares ([anomaly_service.py](backend/app/services/anomaly_service.py)):

### Camada 1 — Detectores comportamentais ([behavior_analyzer.py](backend/app/services/behavior_analyzer.py))

Sete detectores baseados em regras e no histórico da máquina:

| Detector | O que identifica |
|---|---|
| `memory_leak` | Processo com crescimento contínuo de memória (vazamento) |
| `cpu_loop` | Processo travado consumindo CPU alta sustentada |
| `ddos_indicator` | Pico abrupto de conexões/tráfego de rede |
| `unknown_process` / `suspicious_process` | Processo nunca visto na máquina consumindo recursos, ou com nome da lista de ameaças (xmrig, mimikatz...) |
| `malware_pattern` | Combinação de indicadores típicos de malware (roda de pasta temporária, sem linha de comando, privilegiado + CPU alta, etc.) |
| `resource_abuse` | Aplicação conhecida gastando muito mais que o **seu próprio histórico** |
| `behavioral_change` | Várias métricas mudando bruscamente ao mesmo tempo |

Os detectores usam a tabela `process_baselines`, que **aprende** quais processos são normais em cada máquina (um processo vira "conhecido" após 5 aparições).

### Camada 2 — Machine Learning (Isolation Forest, [ml_service.py](backend/app/services/ml_service.py))

- Um modelo **por máquina**, treinado com o histórico dela (13 features: CPU, RAM, swap, disco, I/O, rede, conexões, load, processos, GPU)
- Começa a funcionar após **100 coletas** e **retreina sozinho a cada 30 coletas** (janela de até 5.000 amostras)
- Detecta desvios estatísticos do comportamento normal *daquela* máquina — coisas que nenhuma regra fixa pegaria

Anomalias duplicadas do mesmo tipo têm *cooldown* de 30 minutos para não inundar o painel.

---

## Explicações por IA

Cada anomalia gera uma explicação em **linguagem simples para leigos**, com: resumo, explicação detalhada (comparando com o comportamento normal da máquina), 3 causas ordenadas da mais provável para a menos, e passos práticos dizendo onde clicar.

A geração usa uma **cadeia de provedores com fallback automático** ([ai_service.py](backend/app/services/ai_service.py)):

```
1. Ollama (LLM local no PC com GPU, ex: qwen2.5:14b — grátis e privado)
        │ se offline/falhar (timeout de conexão: 5s)
        ▼
2. Claude pela CLI (usa a assinatura — dispensa chave de API)
        │ se desativado/falhar
        ▼
3. API em nuvem compatível com OpenAI (Groq etc. — só se houver chave)
        │ se não configurada/falhar
        ▼
4. Análise estática local (causas e recomendações pré-escritas por tipo)
```

O Claude pela CLI é um agente, não só um modelo — e o texto enviado carrega
dado que um atacante controla (nome de processo, linha de comando). Por isso
ele roda **só gerando texto**: nenhuma ferramenta, nenhum servidor MCP, nenhuma
configuração de usuário (logo nenhum plugin nem hook), com um system prompt
que diz que o pedido é dado, não instrução, e sem as variáveis de ambiente do
backend. Os provedores em nuvem (2 e 3) nunca recebem dados de uma máquina
marcada como "só IA local".

Ou seja: **o sistema nunca fica sem explicação**, mesmo sem GPU e sem internet. O campo `model_used` da explicação registra qual provedor respondeu. As explicações são geradas de forma assíncrona (fila serial) para não travar a ingestão de métricas.

Cada explicação também traz recursos que a maioria das ferramentas não tem:

- **Números conferidos**: cada valor citado pela IA é checado contra os dados reais; se ela inventar um número, a resposta é rejeitada e o próximo provedor é tentado (o painel mostra o selo "X/Y números conferidos").
- **Nível de linguagem** (simples / intermediário / técnico), trocável por aviso, e passos específicos para a versão do sistema (Windows 10 ≠ 11 ≠ Linux).
- **Contrafactual**: "Se você fechar o Chrome, a memória cai de 91% para ~48%" — calculado dos processos reais, não imaginado.
- **Memória de incidentes**: "Isso já aconteceu 4 vezes, quase sempre segunda de manhã" e "da última vez, a causa foi o backup" (registrada pela própria pessoa ao resolver).
- **Transparência**: qual IA leu os dados, o destino (local/nuvem) e o prompt exato, em "O que foi enviado sobre mim".

---

## Além do básico

O que este projeto tem e ferramentas parecidas (Zabbix, Netdata, PRTG, NinjaOne) não costumam ter — ou só oferecem a técnicos, em planos pagos:

**Aprender com o usuário**
- **"Isso é normal para mim"** vira regra da máquina (por programa, por tipo ou por faixa de horário), marca o programa como conhecido e deixa o detector responsável menos sensível — o sistema aprende de verdade, em vez de só silenciar.
- **Resolução verificada**: depois de "resolvido", o sistema confere as próximas leituras e confirma ("a memória voltou ao normal") ou reabre sozinho.
- **Passo a passo adaptativo**: a pessoa marca "fiz, não resolveu" e a IA gera o próximo passo, sem repetir o que já falhou.
- **Modo "estou fazendo algo pesado"** (bandeja ou painel): suspende avisos de desempenho e tira as leituras do treino.
- **Faixa do normal por máquina e por hora** e limites que se recalibram pelo feedback.

**Detecção mais inteligente**
- **Incidentes com cadeia de causa**: "disco cheio → memória virtual → lentidão → CPU alta", uma história em vez de quatro avisos soltos.
- **Previsões**: quando o disco enche, quando a bateria chega ao fim da vida útil, em quanto tempo um vazamento esgota a memória.
- **O que o modelo viu**: contribuição de cada métrica na nota do Isolation Forest (hora e dia da semana entram como features — o backup das 3h deixa de ser anomalia).
- **Tendência de refrigeração** ("hora de limpar a ventoinha"), **desligamento inesperado** (Event ID 41 / journalctl), **saúde do disco (SMART)** e **erros de hardware**.
- **Identidade por caminho, hash e assinatura**, não só nome: pega `svchost.exe` fora de System32, nomes imitados (`scvhost.exe`), Word abrindo PowerShell, comandos ofuscados, **arquivos-isca contra ransomware** e **beaconing** (contato periódico com um servidor).
- **Coleta adaptativa**: acelera quando algo desvia, desacelera na bateria/ocioso.

**Agir, não só avisar** — encerrar processo, limpar temporários, pausar sincronização, **isolar da rede**, tudo com um clique a partir do aviso e registrado; **caixa-preta** (os minutos antes do aviso em alta resolução) e **replay**.

**Automação com autonomia graduada** — uma regra nasce em "só sugerir"; subir para "pedir confirmação" ou "fazer sozinho e avisar" é decisão explícita do dono. Mesmo no nível automático a ação é **anunciada antes**, com uma janela para cancelar, teto por dia, modo de ensaio e uma lista de ações menor que a manual (isolar a rede nunca é automático). Ferramenta de gestão remota paga automatiza há anos — o que falta nelas é o degrau.

**Saber quando não sabe** — o sistema mede se o normal que aprendeu ainda descreve a máquina (divergência de Jensen-Shannon entre a janela de treino e as leituras recentes) e **diz isso em português**: "estou reaprendendo o normal deste computador". Monitoramento comum não conta ao usuário que a régua envelheceu; simplesmente passa a errar.

**Risco de falha de peça em porcentagem** — SMART, ciclos de bateria, temperatura, idade e erros de hardware viram uma frase acionável: "este disco tem cerca de 18% de chance de dar problema nos próximos 90 dias — faça backup hoje", com a conta aberta embaixo.

**A mesma atualização em várias máquinas** — "depois do KB5034123, 6 dos seus 12 computadores ficaram mais lentos". Uma piora isolada é indistinguível de coincidência; a repetição entre máquinas é o que separa acaso de causa.

**Registro inviolável** — cada aviso, ação e automação entra num livro encadeado por hash. Adulterar um registro antigo quebra a cadeia dos seguintes, e a verificação diz exatamente onde. Dá para baixar o relatório e anexar a um chamado.

**Não fica cego sem o servidor** — o agente mantém a faixa do normal localmente e guarda em disco as leituras que não conseguiu enviar, reenviando-as em ordem **com a hora original** quando a conexão volta. O período sem rede deixa de ser um buraco no histórico.

**No celular** — o painel é instalável pela tela inicial (PWA) e recebe as notificações do sistema com o aplicativo fechado, sem loja e sem aplicativo nativo para manter. Exige HTTPS: em `http://` de rede local o navegador não oferece nem a instalação nem as notificações (só `localhost` é exceção) — a tela explica isso e indica as saídas. Telegram e e-mail não dependem de certificado.

**Vários computadores** — comparação com pares ("usa 3× mais memória que os outros 12 iguais"), **detecção de surto** (mesmo programa novo em várias máquinas), reputação coletiva anônima de executáveis e **conselheiro de upgrade** ("+8 GB teriam evitado 80% dos avisos").

**Conversa e diário** — **"Pergunte ao seu computador"** (chat que consulta os dados por ferramentas) e o **diário semanal** em texto corrido.

**Notificações sem excesso** — Telegram com botões de resposta, e-mail, horário silencioso, agrupamento, resumo diário e "só avisar se persistir".

**Privacidade** — política de IA por máquina (qualquer / só local / sem IA), remoção de segredos na origem, e a tela "o que foi enviado sobre mim" (LGPD).

**Energia** — consumo estimado em R$ e CO₂, por máquina e por programa, e detecção de desperdício.

**Para a pesquisa** — avaliação das explicações (👍/👎 e IA-juíza, comparando Claude × Ollama × Groq) e **modo demonstração**, que injeta anomalias pelo painel — passando pela mesma detecção das reais — para apresentar à banca sem travar um computador de verdade. Além disso:

- **Estudo de compreensão com pessoas**: cada participante vê os mesmos avisos, metade com a explicação da IA e metade só com os números, em ordem sorteada; o sistema cronometra, corrige e aplica o SUS no fim, com teste estatístico e exportação em CSV. É a única medida do projeto que não vem do sistema avaliando a si mesmo.
- **Ablação das camadas**: os mesmos cenários rodados só com regras, só com o modelo e com os dois — a resposta em número para "o Isolation Forest acrescenta alguma coisa?".
- **Validação por retenção temporal**: treino na primeira parte do histórico, medição na parte final, comparando três detectores nos mesmos dados — Isolation Forest, One-Class SVM (os dois algoritmos da proposta, com a mesma suposição sobre a fração de anomalias) e um limiar fixo de três desvios. Duas injeções de anomalia: várias medidas ao mesmo tempo (o caso do minerador, que todos acertam) e **uma medida só, deslocada em 1, 2, 3 e 5 desvios-padrão** — que é onde os detectores se diferenciam, e onde o veredito compara nível a nível.
- **Benchmark reproduzível**: o relógio virtual dos cenários termina sempre na quarta-feira mais recente às 15h. O modelo usa hora e dia da semana como atributos, e ancorado em "agora" o mesmo código dava números diferentes conforme a hora em que se rodava.
- **Fidelidade da explicação**: cada "se você fechar o Chrome, a memória cai para 48%" é conferido contra a leitura seguinte à ação, e a taxa de acerto sai por provedor. Medir se a IA **estava certa**, e não se o texto pareceu bom.

---

## Tecnologias

| Camada | Stack |
|---|---|
| Backend | Python, FastAPI, SQLAlchemy, PostgreSQL, scikit-learn (Isolation Forest), httpx, python-jose (JWT), WebSockets |
| Frontend | React 18, TypeScript, Vite, TailwindCSS, Recharts, axios, react-router |
| Agente | Python, psutil, pystray (bandeja), pynvml/GPUtil/WMI (GPU) |
| IA | Ollama (local) e/ou Groq (nuvem, API compatível com OpenAI) |
| Infra | Docker Compose (PostgreSQL, backend, frontend com Nginx, agente opcional, Ollama opcional) |

---

## Estrutura do projeto

```
TCC/
├── docker-compose.yml        # Orquestra tudo (db, backend, frontend, agent, ollama)
├── .env.example              # Modelo de configuração — copie para .env
├── start.sh / start.ps1      # Scripts de inicialização rápida
│
├── agent/                    # AGENTE (roda nos computadores monitorados)
│   ├── agent.py              # Loop principal: pareamento, bandeja, comandos, envio
│   ├── collector.py          # Coleta via psutil (CPU/RAM/disco/rede/GPU/processos)
│   ├── privacy.py            # Remove senhas/tokens ANTES de os dados saírem
│   ├── sensors.py            # Hash e assinatura de executáveis, tempo ocioso, SO, discos
│   ├── security.py           # Arquivos-isca, beaconing, novos processos, desligamento, SMART
│   ├── inventory.py          # Programas instalados, atualizações, drivers
│   ├── actions.py            # Executa comandos do painel (encerrar, limpar, isolar)
│   ├── blackbox.py           # Caixa-preta em memória + fotografia forense
│   ├── updater.py            # Autoatualização pelo manifesto do servidor
│   ├── localguard.py         # Faixa do normal local + fila em disco quando o servidor cai
│   └── requirements.txt
│   #  Os módulos acima são opcionais: se faltar algum, o agente roda sem
│   #  aquela funcionalidade em vez de falhar.
│
├── backend/
│   ├── app/
│   │   ├── main.py           # App FastAPI + registro das rotas
│   │   ├── config.py         # Todas as configurações (lidas do .env)
│   │   ├── database.py       # Engine e sessão SQLAlchemy
│   │   ├── models/           # Tabelas (User, Machine, Metric, Anomaly, Incident,
│   │   │                     #   AgentCommand, Notification, Report, ProcessIdentity...)
│   │   ├── schemas/          # Modelos Pydantic (entrada/saída da API)
│   │   ├── routers/
│   │   │   ├── auth.py       # Registro, login, login com Google
│   │   │   ├── machines.py   # CRUD de máquinas + pareamento (enroll)
│   │   │   ├── metrics.py    # Ingestão de métricas + consulta + faixa aprendida
│   │   │   ├── anomalies.py  # Avisos, contexto, feedback, passos, caixa-preta
│   │   │   ├── actions.py    # Ações de 1 clique, diagnóstico e modo atividade pesada
│   │   │   ├── chat.py       # "Pergunte ao seu computador"
│   │   │   ├── insights.py   # Previsões, energia, upgrade, mudanças, comparação
│   │   │   ├── account.py    # Preferências, notificações, Telegram, privacidade
│   │   │   ├── share.py      # Link temporário para o técnico (público)
│   │   │   ├── demo.py       # Modo demonstração
│   │   │   ├── agent_files.py# Distribuição do agente, install.sh, manifesto
│   │   │   ├── agent_api.py  # Comandos, caixa-preta, eventos, "tchau" do agente
│   │   │   ├── explanations.py # Regenerar, reescrever por nível, avaliar
│   │   │   ├── playbooks.py  # Automações e o freio delas (confirmar/cancelar)
│   │   │   ├── audit.py      # Livro encadeado e verificação da cadeia
│   │   │   ├── study.py      # Estudo de compreensão com participantes
│   │   │   └── ws.py         # WebSockets (tempo real)
│   │   ├── services/
│   │   │   ├── anomaly_service.py    # Orquestra a detecção — TODO aviso nasce aqui
│   │   │   ├── behavior_analyzer.py  # Os detectores comportamentais
│   │   │   ├── ml_service.py         # Isolation Forest por máquina
│   │   │   ├── llm.py                # Camada única de IA (privacidade, redação, auditoria)
│   │   │   ├── ai_service.py         # Explicações: fatos citáveis e checagem de números
│   │   │   ├── feedback.py           # Regras "isso é normal" e calibração
│   │   │   ├── incidents.py          # Cadeia de causa e efeito
│   │   │   ├── conditions.py         # "O problema ainda está acontecendo?"
│   │   │   ├── resolution.py         # Resolução verificada
│   │   │   ├── notifications.py      # Política de excesso + Telegram/e-mail
│   │   │   ├── forecasting.py        # Disco, bateria, vazamento
│   │   │   ├── trends.py             # Refrigeração e impacto de mudanças
│   │   │   ├── fleet.py              # Comparação, surto e conselho de upgrade
│   │   │   ├── diary.py              # Diário semanal
│   │   │   ├── energy.py             # Consumo, custo e desperdício
│   │   │   ├── chat.py + chat_tools.py # Conversa com consultas aos dados
│   │   │   ├── scheduler.py          # 18 rotinas periódicas (com medição em /metrics)
│   │   │   ├── drift.py              # O normal aprendido ainda descreve a máquina?
│   │   │   ├── hardware_risk.py      # Risco de falha de peça, em % e em português
│   │   │   ├── playbooks.py          # Automação com autonomia graduada
│   │   │   ├── integrity.py          # Livro de auditoria encadeado por hash
│   │   │   ├── fidelity.py           # A IA acertou o efeito que previu?
│   │   │   ├── ml_eval.py            # Retenção temporal (ROC/AUC) e ablação das camadas
│   │   │   ├── study.py              # Estudo com pessoas: sorteio, tempo, SUS, estatística
│   │   │   ├── change_correlation.py # A mesma atualização piorando várias máquinas
│   │   │   ├── push.py               # Web Push (avisos no celular)
│   │   │   └── explanation_queue.py  # Fila assíncrona de explicações
│   │   └── core/             # Segurança, migrações automáticas, redação, rótulos
│   ├── ml/train_all.py       # Treino manual de todos os modelos
│   ├── migrate.py            # Migração manual (o backend já migra sozinho na subida)
│   └── tests/                # Testes (pytest) — backend, serviços e agente
│
└── frontend/                 # Painel: além do dashboard, as páginas
    #   /pergunte (chat), /machines/:id (previsões, energia, diário, mudanças,
    #   upgrade, programas, privacidade), /pesquisa (qualidade das explicações),
    #   /demonstracao e /compartilhado/:token (pública, para o técnico)
    └── src/
        ├── pages/            # Dashboard, Machines, Anomalies, AnomalyDetail, Login, Register
        ├── components/       # Layout, cards, gráficos, badges
        ├── context/          # AuthContext (sessão do usuário)
        ├── hooks/            # usePolling, useWebSocket
        ├── services/api.ts   # Cliente da API (axios)
        ├── utils/installers.ts # Gera instaladores/desinstaladores personalizados
        └── types/            # Tipos TypeScript + traduções dos tipos de anomalia
```

---

## Como rodar o sistema

### Pré-requisitos

- Docker e Docker Compose
- (Opcional, para IA local) GPU NVIDIA + drivers, na máquina que rodará o Ollama

### Passo a passo

```bash
# 1. Clone e entre no projeto
git clone https://github.com/VitorApLavezzo/TCC.git
cd TCC

# 2. Crie sua configuração
cp .env.example .env
#    → edite o .env (veja a seção "Configuração" abaixo)

# 3. Suba os serviços
docker compose up -d --build

# (com Ollama local no mesmo host, se tiver GPU NVIDIA:)
docker compose --profile local-ollama up -d --build
```

Acesse:

| Serviço | Endereço |
|---|---|
| Painel (frontend) | http://localhost:3000 |
| API (backend) | http://localhost:8000 |
| Documentação da API (Swagger) | http://localhost:8000/docs |

> **Importante:** para conectar **outros** computadores, acesse o painel pelo **IP da rede** (ex: `http://192.168.0.10:3000`), não por `localhost` — o endereço usado no navegador é embutido nos instaladores. O painel avisa e pergunta o endereço correto se você estiver em `localhost`.

O banco cria as tabelas automaticamente no primeiro start (sem migração manual). Primeiro acesso: crie sua conta em `/register` ou use o botão do Google.

---

## Conectando computadores (agente)

Na página **Máquinas → Nova Máquina**, o painel gera um **código de pareamento** (uso único, válido por 30 min) e oferece três caminhos:

### 1. Instalador de 2 cliques (Windows e Linux desktop) — recomendado

Baixe o instalador do sistema correspondente e execute na máquina a ser monitorada. Ele faz **tudo sozinho**:

- Verifica/instala o Python (Windows: via winget)
- Baixa o agente do próprio servidor
- Instala as dependências
- Faz o pareamento (hostname e SO são detectados automaticamente)
- Configura início automático (pasta Inicializar no Windows; autostart + menu de aplicativos no Linux)
- Inicia o agente com ícone na bandeja

A máquina aparece no painel em segundos. O código nunca precisa ser digitado.

### 2. Servidor sem interface gráfica (uma linha via SSH)

```bash
curl -fsS "http://SEU-SERVIDOR:3000/api/agent/install.sh?code=XXXX-XXXX&server=http://SEU-SERVIDOR:3000" | bash
```

Instala em modo headless (sem bandeja) com reinício automático via `cron @reboot`. O comando pronto para copiar aparece no painel.

### 3. Manual (avançado)

```bash
cd agent && pip install -r requirements.txt
python agent.py    # ele pedirá o código de pareamento
```

### Como o pareamento funciona por dentro

1. Painel gera um código (`POST /api/machines/enroll-code`, autenticado)
2. O agente troca o código pelo token definitivo (`POST /api/machines/enroll`), enviando hostname/SO detectados — o backend cria a máquina
3. O agente salva token + endereço do servidor em `agent_config.json` e nunca mais pede nada
4. A cada início, o agente **valida o token** com o servidor; se foi revogado (ex: banco recriado), descarta o config e re-pareia

---

## Gerenciando as máquinas

Na página **Máquinas**, cada computador tem:

- **Pausar/Retomar coleta** (⏸/▶) — o servidor passa a descartar os dados sem desconectar o agente
- **Reinstalar** — baixa instalador com o token embutido (sem código, sem validade)
- **Como remover o monitoramento** — tutorial + **desinstalador de 2 cliques** que encerra o agente, apaga todos os arquivos do computador e **remove a máquina do painel automaticamente** (via `DELETE /api/agent/self`, autenticado pelo próprio token)
- **Lixeira** — remove a máquina apenas do painel (o agente instalado se desativa ao perceber o token inválido)

No computador monitorado:

- **Parar**: clique no ícone da bandeja → **Sair**
- **Modo "estou fazendo algo pesado"**: bandeja → escolha a duração (suspende avisos de desempenho; segurança continua)
- **Iniciar de novo**: menu de aplicativos → "AnomalyDetect Agent" (Linux) ou Menu Iniciar → "AnomalyDetect Agent" (Windows)
- Arquivos: `~/.anomalydetect` (Linux) ou `%LOCALAPPDATA%\AnomalyDetect` (Windows); log em `agent.log`

### A pasta `_AnomalyDetect_protecao`

O agente cria uma pasta com esse nome dentro de **Documentos** e **Imagens**, com
dois arquivos-isca e um `LEIA-ME.txt` explicando o que são. Ninguém usa esses
arquivos — então, se algum for alterado ou apagado, é sinal de que um programa
está mexendo nos arquivos da pessoa sem permissão (sequestro de dados), e o
painel recebe um aviso crítico na hora.

Ela fica **visível de propósito**: muitos programas de sequestro pulam arquivos
ocultos, e uma isca oculta poderia nunca disparar. O desinstalador remove a
pasta junto com o resto.

### Atualização do agente

O servidor publica um manifesto com o hash de cada arquivo do agente
(`GET /api/agent/manifest`). A cada 6 horas o agente compara com o que tem,
baixa só o que mudou — conferindo o hash antes de trocar o arquivo — e se
reinicia. Ou seja: **funcionalidade nova chega às máquinas já instaladas sem
passar o instalador de novo em cada uma**.

---

## Configuração (.env)

Copie `.env.example` para `.env`. Principais variáveis:

| Variável | O que faz | Padrão |
|---|---|---|
| `SECRET_KEY` | Assina os tokens JWT — **gere uma chave forte** | — |
| `GOOGLE_CLIENT_ID` | Habilita o login com Google (vazio = botão oculto) | vazio |
| `OLLAMA_BASE_URL` | Onde está o Ollama (container, host ou outra máquina) | `http://ollama:11434` |
| `OLLAMA_MODEL` | Modelo local usado nas explicações | `qwen2.5:14b` |
| `CLOUD_LLM_API_KEY` | Chave da API de nuvem (Groq) — vazio desativa o fallback | vazio |
| `CLOUD_LLM_BASE_URL` / `CLOUD_LLM_MODEL` | Provedor/modelo de nuvem (qualquer API compatível com OpenAI) | Groq / llama-3.3-70b |
| `AGENT_ENROLL_CODE` | Código de pareamento para o container `agent` do compose (1º uso) | vazio |
| `COLLECTION_INTERVAL` | Intervalo de coleta do agente (segundos). Definido, **fixa** o intervalo e desliga o ajuste automático — veja abaixo | 30 |
| `AGENT_ADAPTIVE` | `1` mantém o ajuste automático mesmo com `COLLECTION_INTERVAL` definido | vazio |

**Coleta adaptativa:** sem `COLLECTION_INTERVAL`, o servidor sugere o intervalo a
cada resposta — 10 s quando algo começa a desviar do normal (para a caixa-preta e
as janelas dos detectores ficarem ricas no momento que importa), 60 s com a
máquina parada na bateria, 30 s no resto do tempo. Definir o valor no `.env` é
uma escolha explícita e ela é respeitada: o servidor não sobrescreve.

Parâmetros de detecção (em [config.py](backend/app/config.py), sobrescrevíveis via env): `ANOMALY_SCORE_THRESHOLD`, `MIN_TRAINING_SAMPLES`, `ISOLATION_FOREST_CONTAMINATION`, `TRAINING_WINDOW`, `RETRAIN_EVERY`.

---

## Configurando a IA (Ollama e Claude)

### Opção A — Ollama em outra máquina (ex: seu PC com GPU)

1. Instale o [Ollama](https://ollama.com) e baixe o modelo: `ollama pull qwen2.5:14b`
2. Faça-o aceitar conexões da rede: crie a variável de ambiente `OLLAMA_HOST=0.0.0.0` e reinicie o Ollama (no Windows: Variáveis de Ambiente do sistema; libere a porta 11434 no firewall)
3. No `.env` do servidor: `OLLAMA_BASE_URL=http://IP-DA-MAQUINA:11434`

### Opção B — Ollama no mesmo host do sistema (requer GPU NVIDIA)

`OLLAMA_BASE_URL=http://ollama:11434` e suba com `docker compose --profile local-ollama up -d`.

### Claude pela CLI (reserva quando o PC com GPU está desligado)

Usa a assinatura do Claude já logada na sua máquina — não precisa de chave de
API. A imagem do backend traz a CLI; a credencial vem da pasta apontada por
`CLAUDE_HOST_CONFIG`, montada somente-leitura e copiada para dentro do
container ao subir. No `.env`:

```bash
CLAUDE_CLI_ENABLED=true
CLAUDE_CLI_MODEL=sonnet              # alias do modelo mais recente da família
CLAUDE_HOST_CONFIG=/home/SEU-USUARIO/.claude
```

Apontar para o `~/.claude` de verdade (e não para uma cópia) faz um
`docker compose restart backend` pegar sempre a credencial atual.

### API em nuvem compatível com OpenAI (opcional)

Com uma chave em `CLOUD_LLM_API_KEY` (ex: Groq, gratuita em
https://console.groq.com/keys), entra depois do Claude na cadeia.

---

## Login com Google (opcional)

1. Acesse https://console.cloud.google.com/apis/credentials
2. Crie um **ID do cliente OAuth** do tipo **Aplicativo da Web**
3. Em **Origens JavaScript autorizadas**, adicione todos os endereços usados para acessar o painel (ex: `http://localhost:3000` e `http://192.168.0.10:3000`)
4. Cole o Client ID no `.env` (`GOOGLE_CLIENT_ID=...apps.googleusercontent.com`) e reinicie o backend

O botão aparece na tela de login; a conta é criada automaticamente no primeiro acesso usando o e-mail do Google.

---

## Principais endpoints da API

Documentação interativa completa em `/docs`. Resumo:

| Método/Rota | Autenticação | Função |
|---|---|---|
| `POST /api/auth/register` · `/login` · `/google` | — | Criar conta / entrar |
| `POST /api/machines/enroll-code` | JWT | Gerar código de pareamento |
| `POST /api/machines/enroll` | código | Agente se registra (troca código por token) |
| `GET/PATCH/DELETE /api/machines/{id}` | JWT | Gerenciar máquinas (PATCH `is_active` = pausar) |
| `POST /api/metrics/ingest` | token do agente | Receber métricas (dispara a detecção) |
| `GET /api/metrics/{machine_id}` · `/latest` | JWT | Histórico / última coleta |
| `GET /api/anomalies` · `/{id}` · `/stats/summary` | JWT | Anomalias e estatísticas |
| `PATCH /api/anomalies/{id}/resolve` | JWT | Marcar como resolvida |
| `POST /api/explanations/{id}/regenerate` | JWT | Regenerar explicação da IA |
| `GET /api/anomalies/{id}/context` | JWT | Incidente, avisos parecidos e caixa-preta |
| `POST /api/anomalies/{id}/feedback` | JWT | "É normal para mim" / "era problema" |
| `PATCH /api/anomalies/{id}/step` | JWT | Marcar passo feito / não resolveu (gera o próximo) |
| `POST /api/explanations/{id}/variant` · `/rate` · `/judge` | JWT | Reescrever por nível, avaliar |
| `POST /api/actions/machine/{id}/run` | JWT | Encerrar programa, limpar, isolar da rede |
| `POST /api/actions/machine/{id}/diagnose` | JWT | "Está lento agora, por quê?" (20 s em alta resolução) |
| `POST /api/actions/machine/{id}/focus-mode` | JWT | Modo atividade pesada |
| `POST /api/chat/ask` · `GET /api/chat/message/{id}` | JWT | Pergunte ao seu computador |
| `GET /api/insights/machine/{id}/forecast` · `/energy` · `/upgrade` · `/changes` · `/cooling` | JWT | Análises da máquina |
| `GET /api/insights/fleet/compare` | JWT | Comparação entre os computadores |
| `GET /api/metrics/{id}/baseline` · `/window` | JWT | Faixa do normal aprendida / replay |
| `GET/PATCH /api/account/preferences` · `/notifications` | JWT | Preferências e notificações |
| `GET /api/account/privacy/machine/{id}` | JWT | "O que foi enviado sobre mim" |
| `POST /api/share/anomaly/{id}` · `GET /api/share/view/{token}` | JWT / — | Pacote para o técnico (visualização pública) |
| `GET /api/evaluation/summary` | JWT | Qualidade das explicações por provedor |
| `GET /api/evaluation/fidelity` · `/anomaly/{id}/fidelity` | JWT | A IA acertou o efeito que previu? |
| `GET /api/evaluation/holdout/{machine_id}` | JWT | Validação por retenção temporal (ROC/AUC) do modelo |
| `POST/GET /api/evaluation/ablation` | JWT | Cenários rodados só com regras, só com modelo e com os dois |
| `GET /api/insights/machine/{id}/drift` · `/hardware-risk` | JWT | Deriva do modelo / risco de falha das peças |
| `GET /api/insights/fleet/changes` | JWT | Atualizações que pioraram várias máquinas |
| `GET/POST/PATCH/DELETE /api/playbooks` · `/runs` · `/runs/{id}/decide` | JWT | Automações e o freio delas |
| `GET /api/audit/entries` · `/verify` · `/report` | JWT | Livro encadeado e verificação da cadeia |
| `POST /api/study/sessions` · `/answer` · `/finish` · `GET /api/study/results` | JWT | Estudo de compreensão com participantes |
| `GET /api/account/push/config` · `POST /push/subscribe` · `/push/test` | JWT | Avisos no celular (Web Push) |
| `GET /metrics` | — | Métricas do serviço no formato do Prometheus |
| `POST /api/demo/start` | JWT | Modo demonstração |
| `GET /api/agent/download/{arquivo}` · `/install.sh` · `/manifest` | — | Distribuição e atualização do agente |
| `GET /api/agent/commands` · `POST /api/agent/blackbox` · `/events` · `/goodbye` | token do agente | Canal de tempo de execução do agente |
| `GET /api/agent/validate-token` · `DELETE /api/agent/self` | token do agente | Validar token / auto-remoção |
| `WS /ws/machine/{id}` · `/ws/user` | JWT (query) | Métricas e anomalias em tempo real |

---

## Operação: observabilidade, CI, backup e segurança

**Métricas do serviço.** `GET /metrics` expõe, no formato de texto do
Prometheus e sem dependência nova, contadores de requisições por rota, e — o
que mais importa aqui — a saúde das 18 rotinas do agendador: quantas vezes
cada uma rodou, quanto demorou e **há quantos segundos ela não termina bem**.
Uma rotina que parou de rodar aparece como idade crescendo, que é a única
forma de notar a ausência de algo que deveria acontecer sozinho. A rota é
aberta (não há dado de usuário nela); num servidor público, feche-a no Nginx.

**Integração contínua.** [`.github/workflows/ci.yml`](.github/workflows/ci.yml)
roda, a cada push e pull request, os testes do backend (`pytest`), os testes do
painel (`vitest`) e a verificação de tipos com o build (`tsc && vite build`).

**Backup do banco.** O serviço `backup` do compose faz um `pg_dump` a cada 6
horas em `./backups` (fora do git: tem dados das máquinas monitoradas) e guarda
14 dias (`BACKUP_INTERVAL_HOURS`, `BACKUP_KEEP_DAYS`). O dump só ganha o nome
final se terminou, então um arquivo interrompido nunca se passa por válido.
Para restaurar (apaga e recria as tabelas do banco atual). Com
`ON_ERROR_STOP` e `--single-transaction`, uma restauração que falha no meio
desfaz tudo em vez de deixar o banco pela metade:

```bash
docker compose stop backend
gunzip -c backups/anomaly_db-AAAAMMDD-HHMMSS.sql.gz \
  | docker compose exec -T db psql -U postgres -d anomaly_db -v ON_ERROR_STOP=1 --single-transaction
docker compose start backend
```

**Segurança.** O modelo de ameaça — quem é confiado, quanto, e quais riscos
foram aceitos de propósito — está em [SECURITY.md](SECURITY.md). Em resumo:
login, cadastro e pareamento têm limite de tentativas por IP; a lista de
origens do CORS é configurável (`ALLOWED_ORIGINS`); toda ação executada numa
máquina fica lacrada no livro encadeado; e a automação nunca inclui isolar a
rede.

---

## Testes

```bash
# com o sistema rodando: a imagem do backend já traz o pytest
docker compose exec backend python -m pytest

# ou fora do Docker
cd backend
pip install -r requirements.txt -r requirements-dev.txt
pytest tests/ -v
```

Os testes usam SQLite em memória — não precisam do PostgreSQL. Os do agente
acham a pasta dele tanto no checkout quanto no container; os poucos que leem o
código do frontend são pulados no container, com o motivo escrito, e rodam no CI.
Cobrem a API, o motor de detecção, a checagem de números das explicações, a
política de notificações e os módulos do agente (remoção de segredos, arquivos-isca,
beaconing, autoatualização). `tests/test_new_features.py` cobre o que é novo e
erraria em silêncio: o limite de tentativas, a cadeia de auditoria (inclusive
uma adulteração), a medida de deriva, o risco de hardware, a conferência das
previsões, os degraus de autonomia da automação, a nota SUS e a fila de
leituras do agente.

No painel:

```bash
cd frontend
npm install
npm run test     # vitest: formatação e classificação de estado
npm run build    # tsc + vite: verificação de tipos e empacotamento
```

### Teste ponta a ponta com o agente real

```bash
./testing/e2e_local.sh          # sobe o backend e roda o agente de verdade, ~1 min
```

Sobe o backend com SQLite, cria uma conta, gera um código de pareamento e roda o
**agente real** contra ele, conferindo o que chegou: máquina registrada, sistema
detectado, leituras, identidade dos executáveis (caminho, hash, assinatura),
janela do replay e manifesto de atualização. Não precisa de Docker.

Foi escrevendo este teste que apareceram quatro problemas que nenhum teste de
unidade pegaria: o pareamento quebrando com SQLite, os instaladores não baixando
os módulos novos do agente, o inventário pesado travando o laço de coleta e a
caixa-preta varrendo todos os processos a cada 2 segundos.

### Fault injection em container (Linux)

Ver [`testing/cbox-scenarios/`](testing/cbox-scenarios/) — injeta um problema real
(loop de CPU, vazamento, etc.) num container descartável e confere se o sistema
detecta. É o teste mais forte, porque o problema acontece num sistema operacional
de verdade.

---

## Solução de problemas

| Sintoma | Causa provável / solução |
|---|---|
| Instalador falha com "could not connect to localhost:3000" | Instalador foi baixado acessando o painel por `localhost`. Acesse pelo IP da rede e baixe de novo (o painel avisa e pergunta o endereço) |
| Agente loga "Token rejeitado pelo servidor" | Token revogado (ex: banco recriado). O agente descarta o config e re-pareia sozinho no próximo início; se necessário, reinstale com código novo |
| Máquina "Offline" no painel | Agente parado (inicie pelo menu de aplicativos/Menu Iniciar), sem rede, ou IP do servidor mudou (DHCP — considere IP fixo ou Tailscale) |
| Explicação fica em "Analisando com IA..." | Ollama inacessível e sem chave Groq. Configure `CLOUD_LLM_API_KEY` ou verifique o Ollama (`curl http://IP:11434/api/tags`) |
| `model_used` mostra `cloud/...` mas queria o Ollama | Ollama fora do ar ou modelo não baixado (`ollama pull qwen2.5:14b`); confira `OLLAMA_HOST=0.0.0.0` e firewall na máquina do Ollama |
| Ícone da bandeja não aparece (Linux) | Ambiente sem suporte a bandeja (o agente segue funcionando em segundo plano — veja `agent.log`). No GNOME puro, instale a extensão AppIndicator |
| Duas instâncias do agente | Rode o instalador novamente (ele encerra a anterior) ou mate os processos e inicie um só |
| Desinstalador parece não fazer nada | Versões anteriores tinham um defeito: o comando que encerrava o agente casava com a própria linha de comando e se matava antes, deixando o agente rodando e a pasta travada. Baixe o desinstalador de novo pelo painel. Se a mensagem final disser que sobrou uma pasta, execute-o como administrador |
| Sobrou `C:\ProgramData\AnomalyDetect` | É da instalação em massa (GPO). O desinstalador atual já remove as duas pastas; versões antigas só removiam a de usuário |
| Erro de permissão no Docker | `sudo usermod -aG docker $USER` e relogue (ou use `sudo`) |
| Resetar todo o banco | `docker compose down && docker volume rm tcc_postgres_data tcc_ml_models tcc_agent_data && docker compose up -d` (depois re-pareie os agentes) |

---

## Sobre

Projeto desenvolvido como Trabalho de Conclusão de Curso (TCC) por **Vitor Lavezzo**.

O foco do trabalho é unir **detecção de anomalias** (heurísticas + Isolation Forest treinado por máquina) com **IA generativa** (LLM local/nuvem) para transformar alertas técnicos em explicações que qualquer pessoa entende — com atenção especial à experiência de instalação e uso por leigos.
