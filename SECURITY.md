# Modelo de ameaça

Este documento existe porque o AnomalyDetect não é um painel que só lê números:
ele instala um agente com privilégio alto em computadores de outras pessoas e
executa ordens vindas de um servidor. Quem avalia o trabalho tem o direito de
saber exatamente o que é confiado a quem — e onde estão os limites conhecidos.

## O que o sistema protege

1. As métricas e a lista de processos de cada máquina (revelam rotina de uso,
   programas instalados e horários de trabalho de uma pessoa).
2. O token do agente, que autentica uma máquina para sempre.
3. O canal de comandos: a única parte do sistema que **muda** o estado de um
   computador monitorado.

## Quem é confiado, e quanto

| Ator | Confiança | Como é verificado |
|---|---|---|
| Dono da conta | Total sobre as **suas** máquinas | JWT (HS256, 24 h) e `owner_id` conferido em toda rota |
| Agente instalado | Só escreve dados da própria máquina | Cabeçalho `X-Agent-Token`, único por máquina |
| Visitante de link compartilhado | Leitura de **um** aviso, sem login | Token aleatório com prazo (`ShareLink`) |
| Servidor (backend) | Emite ordens que o agente obedece | — (ver "Riscos aceitos") |
| Provedor de IA | Recebe texto já redigido e sem segredos | Política por máquina (`ai_privacy`) + redação de segredos e PII antes do envio |

## Superfície de ataque, e o que a contém

**Rotas abertas a quem não tem conta.** `/api/auth/login`, `/api/auth/register`,
`/api/auth/google` e `/api/machines/enroll`. As quatro têm limite de tentativas
por IP ([ratelimit.py](backend/app/core/ratelimit.py)): 10 logins / 5 min,
5 cadastros / h, 30 pareamentos / h. O IP é o da conexão; `X-Real-IP` só vale
quando a conexão vem do Nginx (`TRUSTED_PROXY_CIDRS`), senão cada cliente
escolheria o próprio balde pelo cabeçalho. O limite é em memória e vale por processo —
com mais de um Uvicorn atrás de um balanceador, o teto efetivo multiplica pelo
número de processos. Para a escala deste trabalho (um processo no Compose) é
suficiente; em produção maior, a mesma interface aceitaria Redis por trás.

**Pareamento.** O código tem uso único e prazo; a chave em massa tem limite de
usos e validade. Quem intercepta um código antes do uso entra como uma máquina
nova na conta da vítima — não lê as outras máquinas, mas polui os dados. Por
isso o código expira em minutos e aparece na tela de quem pediu.

**Token do agente.** Fica em `agent_config.json`, com as permissões do arquivo
como única proteção. Quem lê o disco da máquina monitorada lê o token e pode
enviar métricas falsas por ela. Não pode ler dados de outras máquinas, nem
disparar ações: o canal de comandos só **entrega** ordens ao agente, nunca as
aceita dele. O painel permite revogar (`regenerate-token`).

**Canal de comandos.** É o ponto mais sensível do sistema. O agente é instalado
com Agendador de Tarefas como `SYSTEM` no Windows (`schtasks /ru SYSTEM
/rl highest`) para continuar rodando sem ninguém logado, e executa encerrar
processo, limpar temporários, pausar sincronização e isolar da rede. O que
contém o risco:

- a lista de comandos é fechada e conferida no servidor e no agente
  ([actions.py](backend/app/routers/actions.py),
  [commands.py](backend/app/services/commands.py)) — não existe "execute este
  texto";
- cada ordem tem prazo curto (10 a 60 min): uma ordem de ontem não roda hoje;
- toda ordem fica registrada com quem pediu, quando e qual foi o resultado, e
  entra no livro-caixa encadeado ([integrity.py](backend/app/services/integrity.py)),
  selado com HMAC por uma chave fora do banco: editar, reatribuir ou recalcular
  um registro quebra a cadeia de forma detectável (apagar só as entradas mais
  recentes ainda exige guardar o último hash fora do servidor);
- ação automática (playbooks) roda com teto diário, janela de desfazer e modo
  de ensaio, e nunca é o padrão de uma regra nova.

**Automação.** Um playbook com autonomia `auto` age sem pedir confirmação. É
por isso que ele nasce sempre como `sugerir`, exige mudança explícita do dono,
recusa comandos fora de uma lista ainda menor que a manual (não automatiza
isolar da rede), e guarda a ação anterior para desfazer.

## Riscos aceitos (e por que)

- **O servidor é confiável por construção.** Quem controlar o backend controla
  os agentes. Não há assinatura fim a fim das ordens: o agente confia em quem
  responde no endereço configurado, sobre TLS. Fechar isso exigiria uma chave
  por máquina e assinatura de cada comando — anotado como trabalho futuro.
- **Sem TLS embutido.** O Compose serve HTTP; a implantação real fica atrás de
  um proxy com certificado. Em HTTP puro, token e métricas trafegam em claro —
  e por isso o agente só se autoatualiza por HTTPS, com o servidor na própria
  máquina (localhost) ou com `AGENT_ALLOW_INSECURE_UPDATE=1`: por HTTP na
  rede, quem respondesse no lugar do servidor entregaria código para o agente
  executar como SYSTEM.
- **Token JWT sem revogação.** Um token roubado vale até expirar (24 h). Não há
  lista de revogados nem refresh token.
- ~~**`SECRET_KEY` padrão.**~~ Corrigido: não há mais valor padrão. O backend
  não sobe com chave conhecida ou com menos de 32 caracteres, e `start.sh` /
  `start.ps1` geram uma ao criar o `.env`.
- **`/metrics` é aberto.** Não expõe dado de usuário (só contadores do
  serviço), mas revela volume de uso; num servidor público, fecha-se no Nginx.

## Privacidade (LGPD)

Dado de processo é dado pessoal por inferência: a lista de programas de alguém
diz o que a pessoa faz. O sistema trata isso com política por máquina
(`any` / `local_only` / `no_ai`), remoção de segredos e identificadores na
origem ([redaction.py](backend/app/core/redaction.py)), a tela "o que foi
enviado sobre mim" e retenção configurável — métricas por 120 dias e fotos de
processos por 21, apagadas por rotina automática. O agente pode ser desinstalado
pelo mesmo instalador que o colocou.
