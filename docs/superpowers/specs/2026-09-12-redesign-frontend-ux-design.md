# Redesign do frontend e da UX — AnomalyDetect

Data: 2026-09-12
Estado: aprovado para planejamento

## Problema

O frontend já passou por um redesign visual (commits `decdcaa`, `e96a4d6`) que
produziu um sistema de tokens coerente e uma boa identidade tipográfica. Esse
redesign não atacou o problema real: **a arquitetura de informação**.

O Painel apresenta os quatro níveis de informação simultaneamente. Com dados
completos ele mostra veredito, quatro sinais vitais com sparkline, treze linhas
de dados brutos em três colunas, painel de GPU, medidores de partição, quatro
gráficos, até seis avisos e um rodapé — cerca de 60 unidades de informação e 12
controles interativos, todos no primeiro nível de leitura.

O objetivo do redesign é reduzir a **complexidade percebida** sem reduzir a
capacidade do sistema. Nenhuma funcionalidade é removida; tudo é reorganizado em
níveis de revelação progressiva.

## Restrições

Preservados sem alteração: backend, rotas de API, banco, autenticação, regras de
negócio, coleta do agente, modelos de ML, detecção de anomalias, permissões.

O trabalho é exclusivamente do lado do cliente (`frontend/`). Qualquer
necessidade de mudança no backend deve ser levantada como bloqueio, não
implementada por conta própria.

## Decisões tomadas

1. **Adaptação por número de máquinas.** A interface muda de forma conforme o
   usuário monitore 1, 2–5 ou 6+ computadores.
2. **Identidade visual nova, do zero.** Nova paleta, nova tipografia, novos
   tokens. A regra "todo valor medido é composto em mono" é mantida por mérito
   próprio, não por herança.
3. **As análises hoje escondidas viram "descobertas"** e sobem para o painel,
   condicionalmente.
4. **As superfícies de banca saem do menu principal** para uma área Sistema
   dentro da conta.
5. **Tema escuro permanece o padrão.** O claro é par completo.
6. **O produto não tem cor de marca.** Toda cor significa estado.

---

## Arquitetura de navegação

### Menu

```
PRINCIPAL                          origem
  Situação          /              era "Painel"
  Alertas      [n]  /alertas       era "Avisos"
  Perguntar         /perguntar     era "Pergunte"

CONTEXTUAL — renderizado apenas com 2+ máquinas
  Computadores      /computadores

CONTA                /conta
  Preferências · Notificações · Privacidade · Modo foco · Glossário
  └─ Sistema         /conta/sistema
       Qualidade das explicações    era "/pesquisa"
       Demonstração                 era "/demonstracao"
```

Rotas antigas redirecionam para as novas (`/machines` → `/computadores`,
`/anomalies` → `/alertas`, `/pergunte` → `/perguntar`, `/pesquisa` e
`/demonstracao` → `/conta/sistema`) para não quebrar links salvos.

### Justificativa dos nomes

- **Situação** substitui "Painel": descreve o conteúdo, não o continente. A
  página responde "como está meu computador agora?".
- **Alertas** substitui "Avisos": elimina a ambiguidade de "aviso" em português
  de interface e unifica o vocabulário — o código hoje alterna entre "aviso",
  "anomalia" e "detecção" para a mesma entidade. **Um só termo em toda a
  interface: alerta.**
- **Perguntar** substitui "Pergunte": infinitivo, consistente com os demais
  itens de menu.
- **Pesquisa** é aposentado como rótulo: não é busca nem era pesquisa no sentido
  que entregava. Vira "Qualidade das explicações".

### Adaptação por escala

| | 1 máquina | 2 a 5 | 6 ou mais |
|---|---|---|---|
| Item "Computadores" no menu | oculto | visível | visível |
| Seletor na Situação | nenhum | abas com ponto de estado | seletor + resumo da frota |
| Situação abre em | a única máquina | a última escolhida (persistida) | a última escolhida |

A máquina escolhida é persistida em `localStorage`. Se ela sumir da lista, cai
para a primeira ativa.

---

## Telas

### Situação (`/`)

Cinco elementos no estado normal. Nenhum card, nenhum gráfico.

```
[ abas de máquina — só com 2+ ]

VEREDITO
  Manchete (display, 34px)
  Frase de apoio (corpo)
  Última leitura há N segundos (micro, mute)
  [ faixa do normal — a assinatura ]

INDICADORES
  Processador   Memória   Disco
     16%          43%      75%
    normal       normal   normal

DESCOBERTAS — só quando há alguma
  · O disco enche em ~12 dias
  · A bateria perdeu 18% de capacidade
                              ver todas →

  Ver informações do sistema →
```

**Descobertas** é a promoção das análises hoje presas nas sete abas de
`/machines/:id`. Fontes, em ordem de prioridade de exibição:

| Fonte | Endpoint | Aparece quando |
|---|---|---|
| Previsão de disco | `insightsApi.forecast` | `disk.eta_days` existe |
| Saúde da bateria | `insightsApi.forecast` | `battery.health_now < 80` |
| Vazamento de memória | `insightsApi.forecast` | há item em `leaks` |
| Recomendação de upgrade | `insightsApi.upgrade` | `ready` e há recomendação |
| Mudança com efeito | `insightsApi.changes` | há mudança nos últimos 7 dias com efeito medido |
| Desperdício de energia | `insightsApi.energy` | `waste.sentence` existe |
| Diário da semana | `reportsApi.list` | há relatório não lido |

No painel aparecem no máximo **duas**, as de maior prioridade. Se não houver
nenhuma, **a seção inteira não é renderizada** — nunca uma seção vazia, nunca um
"nenhuma descoberta ainda". "ver todas →" leva a `/descobertas`, que lista todas
as disponíveis em fluxo único, sem abas.

Cada descoberta é uma frase em português já escrita pelo backend (`sentence`).
O frontend não compõe texto a partir de números crus.

Com um problema em aberto, o veredito absorve estado, resumo e ação num bloco
só:

```
▲  A memória está acima do normal
   Começou às 14:32, há 8 minutos

   Este computador costuma usar até 61% de memória a esta
   hora do dia. Agora está em 93%.

   [ Entender o problema ]
```

**Regra estrutural:** estado, resumo e ação são um bloco, nunca três. Não existe
seção "Problemas recentes" no painel — ela repetiria o que o veredito já nomeou.
Havendo mais de um alerta aberto, uma linha discreta: *"e mais N alertas · ver
todos"*.

Um único CTA na página. `Diagnosticar` migra para Informações do sistema; `Modo
foco` migra para a conta.

Os três indicadores são uma linha de texto e número, sem borda e sem card. A
quarta medida de hoje (temperatura/swap) sai do primeiro nível.

### Informações do sistema (`/computadores/:id/sistema`)

Rota própria, não drawer: linkável, com botão voltar, e no celular não exige
sheet. A rota carrega o id da máquina explicitamente para que o link sirva
também no cenário de frota. Com uma máquina só, `/sistema` redireciona para a
rota completa dela.

As treze linhas achatadas de hoje viram três grupos com intenção.

```
← Situação
Informações do sistema · Vitor-PC

MEDIDAS AGORA
  Processador   16%    16 núcleos · 3,4 GHz
  Memória       93%    14,9 GB de 16 GB
  Disco         75%    112 GB livres
  Memória virtual 12%  de 8 GB
  Temperatura   58 °C
  [ GPU e bateria quando existirem ]
  [ partições quando houver mais de uma ]

O QUE ESTÁ RODANDO
  Programas rodando        247
  Fila do processador      1,82   folgado
  Conexões abertas          38

REDE E DISCO
  Enviando / recebendo     1,2 MB/s · 340 KB/s
  Lendo / gravando         8 MB/s · 2 MB/s

  Ver histórico das últimas horas →
  [ Diagnosticar este computador ]
```

O histórico (`/computadores/:id/sistema/historico`) guarda os gráficos. Dos
quatro atuais sobrevivem processador, memória e disco; "conexões de rede" em
gráfico de linha é removido por não sustentar decisão alguma.

### Alertas (`/alertas`)

Nenhum controle antes da primeira informação.

```
Alertas
2 em aberto

▲  Memória acima do normal
   Vitor-PC · há 8 minutos              Entender →
●  Processador em uso prolongado
   Notebook · ontem, 19:04              Entender →

Resolvidos (14)                          Filtrar ⌄
```

Os cinco filtros de hoje (busca, período, severidade, computador, só em aberto)
ficam atrás de "Filtrar", recolhidos por padrão. Quando algum filtro está ativo,
a região abre automaticamente e exibe as fichas de filtro ativo — o
comportamento atual de fichas removíveis é preservado.

Severidade nunca é comunicada só por cor: cada linha traz um símbolo e uma
palavra além do matiz.

### Entender o problema (`/alertas/:id`)

O centro do TCC. Ordem fixa:

```
← Alertas
                          Explicação:  [Simples] Técnica

▲  A memória está sendo usada acima do normal
   Vitor-PC · começou às 14:32, há 8 minutos

O QUE MUDOU
   [ faixa do normal + traço, com o momento da detecção marcado ]
   Normal a esta hora: até 61%        Agora: 93%

POR QUE ISSO ESTÁ ACONTECENDO
   O programa Chrome passou a usar 4,2 GB, três vezes mais
   do que costuma usar.

O QUE VOCÊ PODE FAZER
   □ Fechar as abas que não está usando
   □ Reiniciar o Chrome
   Isso resolveu?   Sim   Não

▸ Dados técnicos
```

Um gráfico só, e ele decide algo: mostra a faixa do normal aprendido contra a
leitura atual.

O seletor **Simples / Técnica** no topo usa `explanationsApi.variant(id, level)`,
que já existe no backend (`LanguageLevel`). É a materialização dos níveis de
informação e um argumento demonstrável na defesa.

`▸ Dados técnicos`, recolhido, guarda: score e modelo, features usadas,
blackbox, replay, cadeia do incidente, avaliação da IA-juíza, ações executadas,
compartilhamento com técnico. Nada é removido do sistema.

### Computadores (`/computadores`)

Só existe com 2+ máquinas. Responde ao estado, não à operação.

Cada linha: nome, estado (ponto + palavra), último contato, alertas em aberto,
coleta pausada quando for o caso. Nada de métricas na lista.

Instalação, reinstalação e desinstalação continuam atrás de expansão na linha,
como hoje. `BulkEnrollPanel` (chaves em lote) migra para
`/computadores/instalacao` — é operação de frota, não estado. `FleetCompare`
migra para lá também.

### Login (`/login`)

Layout em duas partes no desktop, empilhado no celular. À esquerda, a promessa
do produto com a faixa do normal em repouso como elemento visual — o único lugar
fora da aplicação onde a assinatura aparece. À direita, o formulário, com
largura de campo confortável (não os 22rem atuais).

O botão do Google perde a largura fixa de 320px e acompanha a largura do
formulário.

### Conta (`/conta`) e Sistema (`/conta/sistema`)

Conta agrupa: identificação, nível de linguagem preferido, notificações,
privacidade da IA, modo foco, energia, aparência (tema), glossário, sessão.

Sistema agrupa as duas superfícies de banca: qualidade das explicações por
provedor (com a nota da IA-juíza) e demonstração de cenários.

---

## Destino de cada superfície atual

Nada é apagado do sistema. Esta tabela é normativa: se algo não aparece aqui,
é porque não existe hoje.

| Hoje | Destino |
|---|---|
| `/` Painel — veredito | Situação, veredito (bloco único com resumo e ação) |
| `/` — 4 sinais vitais | Situação, 3 indicadores em linha; a 4ª medida desce |
| `/` — painel "Detalhes" (13 linhas) | Informações do sistema, em 3 grupos |
| `/` — GPU, bateria, partições | Informações do sistema, grupo "Medidas agora" |
| `/` — 4 gráficos | Histórico; "conexões de rede" removido |
| `/` — "Avisos recentes" | Removido do painel (o veredito já nomeia) |
| `/` — botão Diagnosticar | Informações do sistema |
| `/` — Modo foco | Conta |
| `/machines/:id` aba Previsões | Descobertas |
| `/machines/:id` aba Diário | Descobertas |
| `/machines/:id` aba Energia | Descobertas + Conta (configuração de tarifa) |
| `/machines/:id` aba Mudanças | Descobertas |
| `/machines/:id` aba Upgrade | Descobertas |
| `/machines/:id` aba Programas | Informações do sistema, grupo "O que está rodando" |
| `/machines/:id` aba Privacidade | Conta › Privacidade, por computador |
| `/machines` lista | `/computadores`, sem métricas na linha |
| `/machines` BulkEnrollPanel | `/computadores/instalacao` |
| `/machines` FleetCompare | `/computadores/instalacao` |
| `/anomalies` filtros | `/alertas`, recolhidos atrás de "Filtrar" |
| `/anomalies/:id` explicação | `/alertas/:id`, com seletor Simples/Técnica |
| `/anomalies/:id` extras | `/alertas/:id`, dentro de "Dados técnicos" |
| `/pesquisa` | `/conta/sistema` |
| `/demonstracao` | `/conta/sistema` |
| `/welcome` | Mantido, com a identidade nova |
| `/compartilhado/:token` | Mantido, público, com a identidade nova |
| `NotificationsBell` | Barra superior |
| `StaleBanner`, `FreshnessTag` | Mantidos, integrados ao veredito |

`MachineDetail` deixa de existir como página de abas. `/machines/:id`
redireciona para `/computadores/:id/sistema`.

---

## Sistema de design

### Cor

Escuro é o padrão. Cinco neutros e três estados. **Não existe cor de marca:**
toda cor da interface significa estado, e a interação é feita com tinta.

```
                ESCURO (padrão)   CLARO (par)
paper           #0E1518           #FAFBFB     chão da página
field           #151C20           #FFFFFF     superfície elevada
rule            #232C31           #E3E7E9     filete e hachura
mute            #8A959B           #5D686E     texto de apoio
ink             #E8EDEF           #10161A     texto principal e botão

ok              #4E9E7A           #1F7A55     normal
warn            #C98A2E           #8A5A08     atenção
crit            #D45A56           #B03A38     problema
```

Botão primário: preenchido com `ink`, texto em `paper`. Link: `ink` sublinhado.
Item de menu ativo: `ink` com peso maior. Foco de teclado: anel de 2px em `ink`
com deslocamento de 2px.

Todo par de texto sobre superfície atinge no mínimo 4.5:1, incluindo estados de
hover. Os três estados são distinguíveis por forma e palavra além da cor.

No tema escuro a hachura recebe contraste maior que o filete comum, porque ali
ela é elemento estrutural e não separador.

### Tipografia

Carregadas por Google Fonts CDN, como as atuais. Todas com Latin Extended para
os acentos do português.

| Papel | Face | Pesos |
|---|---|---|
| Display | Bricolage Grotesque | 600, 700 |
| Corpo | Instrument Sans | 400, 500, 600 |
| Dado | Martian Mono | 400, 450 (eixo `wdth` estreito) |

Display é usado com restrição: apenas o veredito e títulos de página.

```
veredito     34px  Bricolage 650  -0.02em
título       22px  Bricolage 600  -0.015em
leitura      30px  Martian  450   tabular
seção        15px  Instrument 600
corpo        15px  Instrument 400  altura 1.55
apoio        13px  Instrument 400
canal        11px  Instrument 600  caixa alta  0.1em
micro        11px  Instrument 400
```

Regra herdada e mantida: **todo valor medido pela máquina é composto em Martian
Mono** — valor, unidade, horário, identificador técnico, comando. Um valor
sempre parece um valor.

### Layout

- **Barra superior** substitui a lateral. Três destinos não justificam 224px de
  moldura permanente, e a lateral comunica "há muitos lugares para ir". Marca à
  esquerda, links, estado de conexão e conta à direita. No celular, marca mais
  gaveta.
- Coluna única de **760px** para prosa e leituras; a faixa rompe para **1040px**.
  Essa assimetria é a única ideia do layout.
- Ritmo vertical em base 4. Seções separadas por espaço e filete, nunca por
  caixas.
- **Card é reservado a três coisas:** linha de máquina, linha de alerta, modal.
  Nada mais recebe borda com fundo.
- Raio: 4px em controles, 8px em painéis. Sombra: nenhuma em superfícies planas;
  uma sombra suave apenas em sobreposições.

### Assinatura — a faixa do normal

O objeto pelo qual o produto é lembrado. Aparece no topo da Situação (~120px de
altura), na página do alerta e, em repouso, no login.

- A **faixa** é o normal aprendido daquela máquina naquela hora, vindo de
  `metricsApi.baseline()`. É desenhada como **campo hachurado** — padrão SVG de
  traços diagonais, 1px, passo 6px, na cor `rule` — e **não** como tinta
  colorida. A hachura evoca a região levantada de um desenho de engenharia.
- O **traço** do sinal corre por dentro em `mute`, 1.5px.
- **Dentro da faixa: nenhuma cor na tela.**
- **Ao sair da faixa**, o trecho do traço assume `warn` ou `crit` **e a hachura
  para** — aquela região deixou de ser normal conhecido. A ausência da hachura
  comunica tanto quanto a cor.
- Sem baseline aprendido ainda, a faixa usa o limite fixo de `THRESHOLDS` e o
  rótulo diz que o aprendizado está em curso.

Substitui `SignalTrace` e `SignalMark`. A marca do produto passa a ser um recorte
da própria faixa.

### Movimento

Um só momento animado em todo o produto: o traço se desenha da esquerda para a
direita em ~700ms na montagem da Situação. Nada mais anima — o pulso por leitura
recebida que existe hoje é removido.

`prefers-reduced-motion: reduce` entrega o traço já completo.

### Acessibilidade

Piso não negociável: contraste mínimo 4.5:1 em texto, foco visível em todo
elemento interativo, navegação completa por teclado, estados nunca comunicados
só por cor, alvos de toque de no mínimo 44px, rótulos e mensagens de erro
descritivos, `aria-live` nas atualizações de estado.

### Responsividade

No celular a informação é reordenada, não encolhida. Ordem de prioridade:
estado → alertas → ação → indicadores → detalhes. As abas de máquina viram
seletor. A faixa mantém a altura e perde as marcações de eixo.

---

## Vocabulário da interface

Um termo por conceito, em toda a aplicação:

| Conceito | Termo | Nunca |
|---|---|---|
| Detecção de comportamento fora do normal | **alerta** | aviso, anomalia, detecção, evento |
| Máquina monitorada | **computador** | máquina, host, dispositivo |
| Faixa de comportamento aprendido | **o normal deste computador** | baseline, envelope, faixa aprendida |
| Coleta em andamento | **acompanhando** | ativo, coletando, online |
| Coleta interrompida | **pausado** | inativo, desativado |

Botões nomeiam o que acontece: "Entender o problema", "Ver informações do
sistema", "Conectar computador". A ação mantém o mesmo nome do início ao fim do
fluxo.

Estados vazios são convite à ação, não desculpa. Erros dizem o que aconteceu e
como resolver, sem pedir desculpa e sem vaguidão.

---

## Critério de aceitação

O redesign está concluído quando, sem explicação externa, uma pessoa que nunca
usou o sistema consegue: entrar, entender o estado do computador, identificar se
existe problema, entender o que está acontecendo e descobrir onde clicar para
mais detalhes.

Verificações objetivas na FASE 7, comparando antes e depois. As duas primeiras
usam definições explícitas para serem contáveis sem julgamento:

> **Unidade de informação** = um valor, rótulo ou frase distinta que o leitor
> precisa processar. Um indicador ("Memória / 43% / normal") conta como 3.
>
> **Controle** = elemento clicável ou focalizável no corpo da página, excluindo
> a navegação global e o seletor de computador.

- Unidades de informação na Situação, estado normal, uma máquina: **de ~60 para
  no máximo 16**.
- Controles no corpo da Situação: **de 12 para no máximo 3**.
- Itens de menu principal: **de 5 para 3**.
- Controles antes da primeira informação em Alertas: **de 5 para 0**.
- Gráficos no primeiro nível de qualquer tela: **de 4 para 0**.
- Profundidade máxima de aninhamento de caixas com borda: **1**.
- `npm run build` passa sem erro de tipo.
- Nenhuma chamada de `services/api.ts` removida, renomeada ou com assinatura
  alterada — a superfície de API é idêntica antes e depois.
- Toda rota antiga responde com redirecionamento para a nova.

## Fora de escopo

Alterações no backend, no agente, no esquema do banco ou nos modelos de ML.
Novas funcionalidades. Internacionalização. Testes automatizados de frontend (o
projeto não tem nenhum hoje; introduzi-los é trabalho próprio).
