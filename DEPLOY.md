# Colocar o AnomalyDetect no ar (VPS + DuckDNS)

Passo a passo para rodar o sistema numa VPS com HTTPS, usando um endereço gratuito do DuckDNS.
Sobe o mesmo docker-compose do desenvolvimento, com o painel e a API visíveis só de dentro da
VPS. Quem recebe o domínio e cuida do HTTPS é um destes:

- **O Nginx que já existe na VPS**, quando ela tem outros sites: o sistema vira mais um site
  nele, com certificado pelo `certbot`. É o padrão.
- **O Caddy**, quando a VPS é só deste sistema: ele ocupa as portas 80 e 443 e pede e renova o
  certificado sozinho.

**Não desligue um Nginx ou Apache que já esteja na VPS**: os outros sites dependem dele.

Com HTTPS, os agentes passam a se atualizar sozinhos. Pela rede local em HTTP essa atualização
fica desligada, porque um arquivo trocado no caminho viraria código rodando no computador.

## O que é preciso

- Uma VPS com Ubuntu 24.04, **pelo menos 2 GB de RAM** e uns 20 GB de disco. Os contêineres usam
  cerca de 700 MB parados, e o retreino dos modelos sobe isso. Processador ARM (Oracle Cloud) ou
  x86 servem.
- Uma conta no [DuckDNS](https://www.duckdns.org) (entra com Google ou GitHub).
- Para as explicações da IA: o token do Claude CLI (`claude setup-token`) ou uma chave do Groq.
  Na VPS não há GPU para o Ollama.

## 1. Endereço no DuckDNS

1. No site do DuckDNS, crie um subdomínio, por exemplo `anomalydetect`. O endereço fica
   `anomalydetect.duckdns.org`.
2. No campo *current ip* desse subdomínio, coloque o IP público da VPS e clique em *update ip*.
3. Confira de qualquer computador: `ping anomalydetect.duckdns.org` deve responder com o IP da VPS.

O IP de uma VPS normalmente não muda. Se mudar, ou se você trocar de VPS, basta atualizar o IP no
DuckDNS: os agentes continuam usando o mesmo endereço.

## 2. Preparar a VPS

Entre na VPS por SSH e instale o Docker:

```bash
curl -fsSL https://get.docker.com | sudo sh
sudo usermod -aG docker $USER   # saia e entre de novo no SSH para valer
```

Libere as portas 80 e 443 (TCP; a 443 também em UDP) no firewall:

- **No painel do provedor** (grupo de segurança, firewall da nuvem).
- **No Ubuntu**, se o `ufw` estiver ativo: `sudo ufw allow 80,443/tcp && sudo ufw allow 443/udp`.
- **Oracle Cloud** tem as duas camadas. Além da *Security List* da rede (VCN), a imagem Ubuntu
  vem com regras de `iptables` que bloqueiam tudo menos o SSH:

  ```bash
  sudo iptables -I INPUT 6 -m state --state NEW -p tcp --dport 80 -j ACCEPT
  sudo iptables -I INPUT 6 -m state --state NEW -p tcp --dport 443 -j ACCEPT
  sudo iptables -I INPUT 6 -p udp --dport 443 -j ACCEPT
  sudo netfilter-persistent save
  ```

## 3. Baixar o projeto

```bash
git clone https://github.com/VitorApLavezzo/TCC.git
cd TCC
cp .env.example .env
chmod 600 .env
```

## 4. Configurar o `.env`

Abra o `.env` (`nano .env`) e preencha:

| Variável | O que colocar |
|---|---|
| `DOMAIN` | O endereço do DuckDNS, sem `https://`: `anomalydetect.duckdns.org` (acrescente a linha). |
| `SECRET_KEY` | Uma chave aleatória (comando abaixo). **Se for trazer os dados atuais (passo 7), use a mesma do `.env` de hoje**: as sessões e o selo do registro de integridade dependem dela. |
| `POSTGRES_PASSWORD` | Uma senha aleatória (comando abaixo). |
| `CLAUDE_CLI_ENABLED` | `true`, para as explicações virem do Claude CLI. |
| `CLAUDE_CODE_OAUTH_TOKEN` | O token gerado por `claude setup-token` (o mesmo do `.env` de hoje serve). |
| `LLM_LOCAL_FIRST` | `false`: vai direto à nuvem, sem esperar o Ollama, que não existe na VPS. |
| `CLOUD_LLM_API_KEY` | Opcional: chave do Groq, usada se o Claude CLI falhar. |
| `GOOGLE_CLIENT_ID`, `VAPID_*`, `TELEGRAM_BOT_TOKEN`, `SMTP_*` | Copie do `.env` de hoje, se usa esses recursos. |

Para gerar as chaves aleatórias:

```bash
python3 -c "import secrets; print(secrets.token_urlsafe(48))"
```

`PUBLIC_BASE_URL`, `ALLOWED_ORIGINS` e `TRUSTED_PROXY_CIDRS` não precisam ser preenchidas:
`docker-compose.prod.yml` as define a partir de `DOMAIN`.

Com o computador em "privacidade: só IA local", as explicações não vão para o Claude CLI. Na VPS,
onde não há Ollama, essas máquinas ficam com a explicação pronta (sem IA).

## 5. Subir

```bash
echo 'COMPOSE_FILE=docker-compose.yml:docker-compose.prod.yml' >> .env
docker compose up -d --build
```

A primeira linha faz `docker compose up`, `logs` e os demais usarem a configuração de produção;
os comandos abaixo assumem isso. A primeira subida leva alguns minutos (monta as imagens).

O painel e a API ficam em `127.0.0.1:18300` e `127.0.0.1:18301`, visíveis só de dentro da VPS.
Se outra coisa já usa essas portas (`ss -tlnp | grep -E ':1830[01] '` mostra algo), escolha outras
com `APP_LOCAL_PORT` e `API_LOCAL_PORT` no `.env` e use as mesmas no arquivo do site (passo 6).

## 6. HTTPS

### Com o Nginx que já existe na VPS (padrão)

O arquivo `deploy/nginx-anomalydetect.conf` é o site do sistema. Troque o domínio, ative e peça o
certificado (como root):

```bash
cp deploy/nginx-anomalydetect.conf /etc/nginx/sites-available/anomalydetect
sed -i 's/SEU-NOME.duckdns.org/anomalydetect.duckdns.org/' /etc/nginx/sites-available/anomalydetect
ln -s /etc/nginx/sites-available/anomalydetect /etc/nginx/sites-enabled/anomalydetect
nginx -t && systemctl reload nginx
certbot --nginx -d anomalydetect.duckdns.org
```

- Se o `nginx -t` acusar erro, não recarregue: os outros sites continuam como estavam até o
  erro ser corrigido.
- Sem o `certbot`: `apt install -y certbot python3-certbot-nginx`.
- Se o Nginx da VPS não usa `sites-enabled`, copie o arquivo para
  `/etc/nginx/conf.d/anomalydetect.conf` no lugar das duas primeiras linhas e do `ln`.

O `certbot` acrescenta o HTTPS ao site, faz o HTTP virar HTTPS e renova o certificado sozinho.
Se ele não conseguir o certificado, quase sempre é a porta 80 fechada (passo 2) ou o DuckDNS
apontando para outro IP (passo 1).

### Com o Caddy (VPS só deste sistema)

Só quando nada mais usa as portas 80 e 443 na VPS:

```bash
echo 'COMPOSE_PROFILES=caddy' >> .env
docker compose up -d
docker compose logs -f caddy
```

Quando aparecer `certificate obtained successfully`, abra `https://anomalydetect.duckdns.org`.

## 7. Trazer os dados atuais (opcional)

Faça isto **antes de criar qualquer conta** na VPS. No computador de hoje, o serviço `backup` já
guarda cópias em `backups/`. Pegue a mais recente e envie para a VPS:

```bash
scp backups/anomaly_db-AAAAMMDD-HHMMSS.sql.gz usuario@IP-DA-VPS:~/TCC/backups/
```

Na VPS, restaure com só o banco no ar:

```bash
docker compose stop backend
gunzip -c backups/anomaly_db-AAAAMMDD-HHMMSS.sql.gz \
  | docker compose exec -T db psql -U postgres -d anomaly_db -v ON_ERROR_STOP=1 --single-transaction
docker compose start backend
```

O `SECRET_KEY` precisa ser o mesmo do computador de hoje (passo 4). Senão o registro de
integridade acusa adulteração em tudo o que veio do banco antigo.

## 8. Apontar os agentes para o novo endereço

**Se trouxe os dados (passo 7):** os computadores continuam cadastrados, basta trocar o endereço
(`api_url`) no `agent_config.json` de cada um e reiniciar o agente. A troca é feita com Python
porque o agente lê o arquivo em UTF-8, e o PowerShell gravaria em outra codificação.

- **Linux:**

  ```bash
  cd ~/.anomalydetect
  pkill -f .anomalydetect/agent.py
  venv/bin/python -c "import json; p='agent_config.json'; c=json.load(open(p, encoding='utf-8')); c['api_url']='https://anomalydetect.duckdns.org'; json.dump(c, open(p, 'w', encoding='utf-8'), indent=2)"
  nohup venv/bin/python agent.py >/dev/null 2>&1 &
  ```

- **Windows** (PowerShell):

  ```powershell
  cd $env:LOCALAPPDATA\AnomalyDetect
  Stop-Process -Name pythonw -Force
  python -c "import json; p='agent_config.json'; c=json.load(open(p, encoding='utf-8')); c['api_url']='https://anomalydetect.duckdns.org'; json.dump(c, open(p, 'w', encoding='utf-8'), indent=2)"
  wscript "$env:APPDATA\Microsoft\Windows\Start Menu\Programs\Startup\AnomalyDetectAgent.vbs"
  ```

**Se começou do zero:** crie a conta no novo endereço e instale os agentes pelo painel, como
sempre. Os instaladores já saem com o endereço HTTPS.

## 9. Login com Google

No [Google Cloud Console](https://console.cloud.google.com/apis/credentials), abra o ID do
cliente OAuth usado em `GOOGLE_CLIENT_ID` e acrescente `https://anomalydetect.duckdns.org` em
*Origens JavaScript autorizadas*. O Google não aceita IP, só domínio.

## Manutenção

- **Atualizar o sistema:** `git pull && docker compose up -d --build`. O backend não roda com
  `--reload` em produção, então só muda depois disso.
- **Ver erros:** `docker compose logs --tail 100 backend`.
- **Cópias do banco:** ficam em `~/TCC/backups` na própria VPS, a cada 6 horas. De vez em quando,
  copie a mais recente para fora (`scp` para o seu computador): se a VPS sumir, as cópias somem
  junto.
- **Espaço em disco:** cada computador monitorado gera uns 20 MB por dia no banco. A lista de
  programas fica 60 dias e as leituras 120 dias (`PROCESS_SNAPSHOT_RETENTION_DAYS` e
  `METRIC_RETENTION_DAYS` em `backend/app/config.py`).
