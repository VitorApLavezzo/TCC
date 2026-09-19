# Falsos positivos nas primeiras análises e em software de segurança

**Data:** 19/09/2026
**Motivo:** durante os primeiros minutos de monitoramento o sistema avisava sobre
programas do próprio sistema, que sempre estiveram ali; e um antivírus em
varredura foi classificado como possível malware — exatamente o contrário do
que ele é.

## Diagnóstico

Dois defeitos independentes, ambos nos detectores comportamentais (o modelo
estatístico não participa: ele já esperava 100 leituras antes de opinar).

**1. Não havia período de aprendizado.** `detect_new_suspicious_process` só se
continha enquanto *nenhum* processo fosse conhecido. Como `ProcessBaseline.is_known`
vira verdadeiro com 5 aparições, depois de ~5 coletas (2,5 min no intervalo padrão)
a máquina já se considerava conhecida, e todo programa aberto a partir dali virava
`unknown_process`. As duas camadas de detecção usavam réguas incompatíveis: 100
leituras para o modelo, 5 aparições para os detectores.

**2. Assinatura digital só era usada contra o programa.** `detect_malware_pattern`
somava 7 indicadores e acusava com 2. Um antivírus varrendo entrega dois de graça:
`privilegiado_com_cpu_alta` (roda como SYSTEM) e `cpu_com_spike_rede` (baixa
assinaturas). O projeto já tinha `ProcessIdentity.signed/publisher` e
`HashReputation`, e `agent_events` já os usava para segurar alertas de beaconing —
mas os detectores comportamentais não consultavam nada disso. A única leitura da
assinatura era negativa (`unsigned_user_dir`).

Um terceiro defeito apareceu durante o trabalho: `detect_resource_abuse` comparava
o consumo atual com a **média** do processo, exigindo apenas `is_known` (5
aparições). Um programa que fica ocioso e acorda para trabalhar — antivírus,
backup, indexador — tem média baixa e pico alto, então o pico normal dele era
acusado. Pior: o baseline já guardava `max_cpu` e o detector nunca olhava.

## Decisões

### Período de aprendizado

Uma máquina está aprendendo enquanto não tiver **100 leituras E 6 horas de
relógio** — vale a régua mais lenta. As 100 leituras são o mesmo
`MIN_TRAINING_SAMPLES` do modelo; as 6 horas existem porque a coleta é adaptativa
e, a 10 s por leitura, 100 leituras seriam 17 minutos.

A contagem começa na primeira leitura recebida, não no cadastro: quem cadastra a
máquina na sexta e liga o computador na segunda não pode "se formar" com zero
dado só porque o relógio andou.

Durante o aprendizado a anomalia **é criada e aparece no painel**, marcada com
`during_learning`; o que não acontece é a notificação, suprimida pelo mecanismo
que já existia para severidade mínima. Sem digest: um resumo diário cheio de
ruído da fase de aprendizado é o mesmo ruído, adiado.

Atravessam o portão os avisos cuja evidência não depende de histórico
(`LEARNING_EXEMPT`): arquivo-isca de ransomware, programa disfarçado, comando
suspeito, documento abrindo ferramenta do sistema, nome de minerador conhecido.
O critério não é gravidade, é se a evidência precisa de passado para significar
alguma coisa.

Máquinas de demonstração (`is_demo`) nunca estão aprendendo: a demonstração da
banca tem 8 a 20 passos de aquecimento.

### Camada de confiança

Quatro níveis, calculados uma vez por coleta e transportados no
`DetectionContext` (a reputação vem do banco; uma consulta por detector seriam
dez):

| Nível | Critério |
|---|---|
| 0 desconhecido | nada sustenta o executável |
| 1 comum | assinado, **ou** visto em ≥3 máquinas sem reclamação |
| 2 confiável | assinado **e** instalado em pasta de programas do sistema |
| 3 segurança | confiável **e** produto de segurança reconhecido |

Duas regras impedem que isto vire um buraco:

- O nível 3 nunca vem do nome nem do fabricante sozinhos. Sem assinatura válida,
  `MsMpEng.exe` em `Downloads` é nível 0 — e segue pego pelo detector de disfarce.
  Para a Microsoft, que assina metade do que roda num Windows, o rótulo de
  segurança vem do nome do processo do Defender, não do fabricante.
- Executável confirmado como problema por alguém, ou reprovado no VirusTotal,
  cai para 0 por mais bem assinado que seja. Certificado roubado acontece.

No Linux funciona porque o agente já traduz "pertence a um pacote dpkg/rpm" como
assinado, com o nome do pacote como fabricante.

### Indícios concretos vs. circunstanciais

`detect_malware_pattern` passa a separar:

- **circunstanciais** — descrevem o momento: cpu alta + pico de rede,
  privilegiado + cpu alta, ferramenta do sistema + rede;
- **concretos** — são fatos sobre o arquivo: nome de minerador, roda de `Temp`,
  sem linha de comando, não assinado em pasta de usuário.

Regra: **pelo menos um indício concreto, sempre**; e 3 no total (em vez de 2) para
executáveis de confiança ≥ 2, que também perdem o indício
`privilegiado_com_cpu_alta` — um serviço assinado do sistema rodar como SYSTEM é
a definição de serviço, não um indício.

**Custo aceito conscientemente:** um binário legítimo e assinado sendo abusado
(cpu + rede + privilégio, nada concreto) deixa de virar `malware_pattern`. Esse
caso é coberto com evidência real por `suspicious_command` e `suspicious_parent`,
que olham a linha de comando e a árvore de processos. É uma perda, não um lucro.

Observação registrada durante a implementação: para o caso específico do
antivírus, é a regra do indício concreto — não a camada de confiança — que faz
o trabalho. A confiança importa para `unknown_process`, para a severidade de
`resource_abuse` e para o limite de 3 indícios.

### Correções em `detect_resource_abuse`

- Baseline precisa de **20 aparições** (`MIN_BASELINE_SAMPLES`), não 5.
- O consumo precisa superar **o máximo já visto** daquele processo (`max_cpu * 1.2`),
  não a média. "Fora do padrão" passa a significar "mais do que já foi visto
  consumir".
- Software de segurança (nível 3) nasce com severidade `low`: fica registrado e,
  como `min_severity` padrão é `medium`, sai da notificação sozinho.

## Arquivos

Backend: `services/trust.py` e `services/learning.py` (novos);
`services/behavior_analyzer.py`, `services/anomaly_service.py`,
`services/notifications.py`, `core/labels.py`, `models/anomaly.py`,
`schemas/anomaly.py`, `routers/metrics.py`.

Frontend: `types/index.ts`, `components/Verdict.tsx`, `components/AnomalyEvent.tsx`,
`pages/AnomalyDetail.tsx`.

Banco: coluna `anomalies.during_learning`, aplicada automaticamente por
`upgrade_schema` na subida do backend.

## Testes

`tests/test_trust.py` (17), `tests/test_learning.py` (13) e quatro testes de ponta
a ponta em `tests/test_pipeline.py`, incluindo um que roda três cenários da
demonstração até o fim para garantir que ela continua detectando.

Nota de método: dois testes de integração passaram na primeira tentativa por
motivo errado — só o candidato mais grave de cada coleta vira linha no banco, então
asserções do tipo "este tipo não aparece" eram satisfeitas por acidente sempre que
outro detector chegava na frente. Foram reescritos para exigir ausência total de
anomalias e revalidados desligando a fiação de propósito.
