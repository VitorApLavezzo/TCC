"""Camada de confiança: quem merece benefício da dúvida antes de ser acusado.

O caso que originou isto: um antivírus rodando uma varredura é, para um
detector ingênuo, indistinguível de um minerador — roda como SYSTEM, come
processador e fala com a internet. A diferença está na identidade do
executável, não no seu comportamento.
"""
from types import SimpleNamespace

from app.core.security import get_password_hash
from app.models.machine import Machine
from app.models.user import User


def _machine(db, **over):
    u = User(email=f"t{id(db)}@t.com", username=f"u{id(db)}", hashed_password=get_password_hash("x"))
    db.add(u)
    db.flush()
    m = Machine(name="PC", hostname="H", agent_token=f"tok-{id(db)}", owner_id=u.id, **over)
    db.add(m)
    db.flush()
    db.commit()
    return m


def _proc(**over):
    base = {"name": "app.exe", "exe": "C:\\Program Files\\App\\app.exe", "signed": "signed",
            "publisher": "App Inc", "sha256": "a" * 64, "cpu_percent": 5.0, "mem_percent": 2.0,
            "username": "user", "cmdline": "app.exe", "pid": 100, "ppid": 4, "parent_name": "explorer.exe",
            "num_threads": 8, "mem_rss": 1e9, "status": "running"}
    return SimpleNamespace(**{**base, **over})


class TestNiveisDeConfianca:
    def test_antivirus_assinado_em_program_files_e_software_de_seguranca(self, db):
        from app.services import trust
        m = _machine(db)
        proc = _proc(name="avp.exe", exe="C:\\Program Files (x86)\\Kaspersky Lab\\KAV\\avp.exe",
                     signed="signed", publisher="Kaspersky Lab JSC")
        t = trust.evaluate(db, m.id, proc)
        assert t.level == trust.SECURITY
        assert t.is_security_software is True

    def test_defender_e_reconhecido_pelo_nome_do_processo(self, db):
        """A Microsoft assina meio mundo: o fabricante não pode promover sozinho."""
        from app.services import trust
        m = _machine(db)
        defender = _proc(name="MsMpEng.exe", exe="C:\\Program Files\\Windows Defender\\MsMpEng.exe",
                         publisher="Microsoft Windows Publisher")
        outro = _proc(name="notepad.exe", exe="C:\\Program Files\\Bloco\\notepad.exe",
                      publisher="Microsoft Windows Publisher")
        assert trust.evaluate(db, m.id, defender).level == trust.SECURITY
        assert trust.evaluate(db, m.id, outro).level == trust.TRUSTED

    def test_nome_de_antivirus_sem_assinatura_nao_ganha_nada(self, db):
        """Se bastasse o nome, um vírus se chamaria MsMpEng.exe."""
        from app.services import trust
        m = _machine(db)
        proc = _proc(name="MsMpEng.exe", exe="C:\\Users\\x\\Downloads\\MsMpEng.exe",
                     signed="unsigned", publisher=None)
        t = trust.evaluate(db, m.id, proc)
        assert t.level == trust.UNKNOWN
        assert t.is_security_software is False

    def test_assinado_fora_de_pasta_de_programas_e_apenas_comum(self, db):
        from app.services import trust
        m = _machine(db)
        proc = _proc(exe="C:\\Users\\x\\AppData\\Local\\Slack\\slack.exe")
        assert trust.evaluate(db, m.id, proc).level == trust.COMMON

    def test_pacote_do_linux_conta_como_assinado(self, db):
        """No Linux o agente traduz 'pertence a um pacote dpkg/rpm' como assinado."""
        from app.services import trust
        m = _machine(db, os_type="Linux")
        proc = _proc(name="firefox", exe="/usr/lib/firefox/firefox", signed="signed", publisher="firefox")
        assert trust.evaluate(db, m.id, proc).level == trust.TRUSTED

    def test_confirmado_como_problema_perde_toda_a_confianca(self, db):
        # O voto que reprova é o da própria conta (o de outra conta é só opinião)
        from app.models.identity import HashReputation, ReputationVote
        from app.services import trust
        m = _machine(db)
        proc = _proc(name="avp.exe", exe="C:\\Program Files\\Kaspersky Lab\\avp.exe",
                     publisher="Kaspersky Lab JSC", sha256="b" * 64)
        db.add(HashReputation(identity_key="b" * 64, name="avp.exe", local_machines=5, marked_problem=1))
        db.add(ReputationVote(identity_key="b" * 64, owner_id=m.owner_id, kind="problem"))
        db.commit()
        assert trust.evaluate(db, m.id, proc).level == trust.UNKNOWN

    def test_visto_em_varias_maquinas_vira_comum_mesmo_sem_assinatura(self, db):
        # Prevalência é na frota do próprio dono: quatro máquinas dele
        from app.models.identity import ProcessIdentity
        from app.services import trust
        m = _machine(db)
        for i in range(4):
            outra = m if i == 0 else Machine(name=f"PC{i}", hostname=f"H{i}", agent_token=f"tok-{id(db)}-{i}",
                                             owner_id=m.owner_id)
            db.add(outra)
            db.flush()
            db.add(ProcessIdentity(machine_id=outra.id, name="ferramenta.exe",
                                   exe=f"C:\\Users\\x{i}\\ferramenta.exe", sha256="c" * 64))
        db.commit()
        proc = _proc(name="ferramenta.exe", exe="C:\\Users\\x\\ferramenta.exe",
                     signed="unknown", publisher=None, sha256="c" * 64)
        assert trust.evaluate(db, m.id, proc).level == trust.COMMON


class TestMalwarePatternComConfianca:
    """O sintoma que o usuário relatou: antivírus acusado de ser vírus."""

    def _historico(self, db, machine_id, net):
        from datetime import timedelta
        from app.core.timeutil import utcnow
        from app.models.metric import Metric
        agora = utcnow()
        antigas = []
        for i in range(1, 6):
            met = Metric(machine_id=machine_id, cpu_percent=20, mem_percent=40,
                         net_bytes_sent=net, net_bytes_recv=net,
                         timestamp=agora - timedelta(minutes=i))
            db.add(met)
            antigas.append(met)
        atual = Metric(machine_id=machine_id, cpu_percent=70, mem_percent=45,
                       net_bytes_sent=net * 20, net_bytes_recv=net * 20, timestamp=agora)
        db.add(atual)
        db.commit()
        return atual, antigas

    def test_antivirus_varrendo_nao_vira_padrao_de_malware(self, db):
        """SYSTEM + processador alto + baixando assinaturas = dois indícios
        circunstanciais e nenhum concreto. Não acusa."""
        from app.services.behavior_analyzer import DetectionContext, detect_malware_pattern
        from app.services import trust
        m = _machine(db)
        atual, antigas = self._historico(db, m.id, 50000)
        proc = _proc(name="avp.exe", exe="C:\\Program Files (x86)\\Kaspersky Lab\\KAV\\avp.exe",
                     publisher="Kaspersky Lab JSC", username="SYSTEM", cpu_percent=65.0)
        ctx = DetectionContext(trust_levels=trust.evaluate_all(db, m.id, [proc]))
        assert detect_malware_pattern(atual, [proc], antigas, db, ctx) is None

    def test_minerador_dispara_mesmo_assinado_e_em_program_files(self, db):
        """Nome de minerador é indício concreto: confiança não salva."""
        from app.services.behavior_analyzer import DetectionContext, detect_malware_pattern
        from app.services import trust
        m = _machine(db)
        atual, antigas = self._historico(db, m.id, 50000)
        proc = _proc(name="xmrig.exe", exe="C:\\Program Files\\Miner\\xmrig.exe",
                     publisher="Alguem", username="SYSTEM", cpu_percent=95.0)
        ctx = DetectionContext(trust_levels=trust.evaluate_all(db, m.id, [proc]))
        r = detect_malware_pattern(atual, [proc], antigas, db, ctx)
        assert r is not None and r.anomaly_type == "malware_pattern"

    def test_nao_assinado_rodando_de_temp_continua_disparando(self, db):
        from app.services.behavior_analyzer import DetectionContext, detect_malware_pattern
        from app.services import trust
        m = _machine(db)
        atual, antigas = self._historico(db, m.id, 50000)
        proc = _proc(name="update.exe", exe="C:\\Users\\x\\AppData\\Local\\Temp\\update.exe",
                     signed="unsigned", publisher=None, username="x", cpu_percent=80.0)
        ctx = DetectionContext(trust_levels=trust.evaluate_all(db, m.id, [proc]))
        r = detect_malware_pattern(atual, [proc], antigas, db, ctx)
        assert r is not None and r.anomaly_type == "malware_pattern"

    def test_so_indicios_circunstanciais_nao_acusam_nem_sem_confianca(self, db):
        """Mesmo num executável desconhecido: circunstância não é evidência."""
        from app.services.behavior_analyzer import DetectionContext, detect_malware_pattern
        from app.services import trust
        m = _machine(db)
        atual, antigas = self._historico(db, m.id, 50000)
        proc = _proc(name="servico.exe", exe="D:\\apps\\servico.exe", signed="unknown",
                     publisher=None, username="SYSTEM", cpu_percent=60.0)
        ctx = DetectionContext(trust_levels=trust.evaluate_all(db, m.id, [proc]))
        assert detect_malware_pattern(atual, [proc], antigas, db, ctx) is None


class TestProcessoDesconhecido:
    def test_programa_assinado_recem_instalado_nao_e_processo_desconhecido(self, db):
        from app.models.process_baseline import ProcessBaseline
        from app.services.behavior_analyzer import DetectionContext, detect_new_suspicious_process
        from app.services import trust
        from app.models.metric import Metric
        m = _machine(db)
        db.add(ProcessBaseline(machine_id=m.id, process_name="explorer.exe", seen_count=30, is_known=True))
        met = Metric(machine_id=m.id, cpu_percent=30, mem_percent=40)
        db.add(met)
        db.commit()
        proc = _proc(name="novo_editor.exe", exe="C:\\Program Files\\Editor\\novo_editor.exe",
                     publisher="Editor Ltda", cpu_percent=40.0)
        ctx = DetectionContext(trust_levels=trust.evaluate_all(db, m.id, [proc]))
        assert detect_new_suspicious_process(met, [proc], [], db, ctx) is None

    def test_executavel_desconhecido_sem_assinatura_ainda_e_avisado(self, db):
        from app.models.process_baseline import ProcessBaseline
        from app.services.behavior_analyzer import DetectionContext, detect_new_suspicious_process
        from app.services import trust
        from app.models.metric import Metric
        m = _machine(db)
        db.add(ProcessBaseline(machine_id=m.id, process_name="explorer.exe", seen_count=30, is_known=True))
        met = Metric(machine_id=m.id, cpu_percent=30, mem_percent=40)
        db.add(met)
        db.commit()
        proc = _proc(name="estranho.exe", exe="C:\\Users\\x\\Downloads\\estranho.exe",
                     signed="unsigned", publisher=None, cpu_percent=40.0)
        ctx = DetectionContext(trust_levels=trust.evaluate_all(db, m.id, [proc]))
        r = detect_new_suspicious_process(met, [proc], [], db, ctx)
        assert r is not None and r.anomaly_type == "unknown_process"


class TestAbusoDeRecurso:
    def _baseline(self, db, machine_id, **over):
        from app.models.process_baseline import ProcessBaseline
        campos = {"machine_id": machine_id, "process_name": "app.exe", "seen_count": 40, "is_known": True,
                  "avg_cpu": 3.0, "max_cpu": 50.0, "avg_mem_percent": 2.0, "max_mem_percent": 5.0}
        b = ProcessBaseline(**{**campos, **over})
        db.add(b)
        db.commit()
        return b

    def test_nao_avisa_abaixo_do_maximo_ja_visto(self, db):
        """Consumir 40% um programa que já chegou a 50% não é 'fora do padrão'."""
        from app.models.metric import Metric
        from app.services.behavior_analyzer import DetectionContext, detect_resource_abuse
        m = _machine(db)
        self._baseline(db, m.id)
        met = Metric(machine_id=m.id, cpu_percent=45, mem_percent=40)
        db.add(met)
        db.commit()
        proc = _proc(cpu_percent=40.0)
        assert detect_resource_abuse(met, [proc], [], db, DetectionContext()) is None

    def test_avisa_quando_supera_o_maximo_ja_visto(self, db):
        from app.models.metric import Metric
        from app.services.behavior_analyzer import DetectionContext, detect_resource_abuse
        m = _machine(db)
        self._baseline(db, m.id)
        met = Metric(machine_id=m.id, cpu_percent=90, mem_percent=40)
        db.add(met)
        db.commit()
        proc = _proc(cpu_percent=85.0)
        r = detect_resource_abuse(met, [proc], [], db, DetectionContext())
        assert r is not None and r.anomaly_type == "resource_abuse"

    def test_baseline_curto_demais_nao_serve_de_referencia(self, db):
        """Cinco aparições não são uma média — era o que acusava o antivírus."""
        from app.models.metric import Metric
        from app.services.behavior_analyzer import DetectionContext, detect_resource_abuse
        m = _machine(db)
        self._baseline(db, m.id, seen_count=5, avg_cpu=1.5, max_cpu=3.0)
        met = Metric(machine_id=m.id, cpu_percent=45, mem_percent=40)
        db.add(met)
        db.commit()
        proc = _proc(cpu_percent=40.0)
        assert detect_resource_abuse(met, [proc], [], db, DetectionContext()) is None

    def test_varredura_de_antivirus_nasce_com_severidade_baixa(self, db):
        """Software de segurança consumindo recursos é o programa trabalhando:
        fica registrado, mas `low` já é filtrado da notificação por padrão."""
        from app.models.metric import Metric
        from app.services.behavior_analyzer import DetectionContext, detect_resource_abuse
        from app.services import trust
        m = _machine(db)
        self._baseline(db, m.id, process_name="avp.exe")
        met = Metric(machine_id=m.id, cpu_percent=90, mem_percent=40)
        db.add(met)
        db.commit()
        proc = _proc(name="avp.exe", exe="C:\\Program Files (x86)\\Kaspersky Lab\\KAV\\avp.exe",
                     publisher="Kaspersky Lab JSC", cpu_percent=85.0)
        ctx = DetectionContext(trust_levels=trust.evaluate_all(db, m.id, [proc]))
        r = detect_resource_abuse(met, [proc], [], db, ctx)
        assert r is not None and r.severity == "low"


class TestConfiancaNoCaminhoDoModelo:
    """O modelo estatístico marcava a varredura do antivírus como leitura fora
    do padrão — o que ela é — e virava aviso. A camada de confiança só
    alcançava os detectores comportamentais."""

    def test_varredura_de_antivirus_nasce_com_severidade_baixa(self, db):
        from app.services.anomaly_service import ml_severity
        from app.services import trust
        proc = _proc(name="avp.exe", exe="C:\\Program Files (x86)\\Kaspersky Lab\\KAV\\avp.exe",
                     publisher="Kaspersky Lab JSC")
        t = trust.evaluate(db, _machine(db).id, proc)
        assert ml_severity("disk_activity", "high", t) == "low"

    def test_programa_comum_nao_ganha_desconto(self, db):
        """A regra é estreita de propósito: qualquer programa assinado
        rebaixando o modelo abriria espaço para binário sequestrado."""
        from app.services.anomaly_service import ml_severity
        from app.services import trust
        proc = _proc(name="chrome.exe", exe="C:\\Program Files\\Google\\Chrome\\chrome.exe",
                     publisher="Google LLC")
        t = trust.evaluate(db, _machine(db).id, proc)
        assert ml_severity("network_spike", "high", t) == "high"

    def test_aviso_de_seguranca_nunca_e_rebaixado(self, db):
        from app.services.anomaly_service import ml_severity
        from app.services import trust
        proc = _proc(name="avp.exe", exe="C:\\Program Files (x86)\\Kaspersky Lab\\KAV\\avp.exe",
                     publisher="Kaspersky Lab JSC")
        t = trust.evaluate(db, _machine(db).id, proc)
        assert ml_severity("malware_pattern", "critical", t) == "critical"

    def test_sem_processo_responsavel_nada_muda(self, db):
        from app.services.anomaly_service import ml_severity
        assert ml_severity("network_spike", "medium", None) == "medium"


class TestCpuLoopComConfianca:
    """Um jogo a 90% de processador não está travado em laço infinito — está
    funcionando como foi projetado. O detector não distinguia carga intensa
    legítima de carga intensa patológica."""

    def _historico(self, db, machine_id, proc_name, cpu):
        from datetime import timedelta
        from app.core.timeutil import utcnow
        from app.models.metric import Metric
        from app.models.process import ProcessSnapshot
        agora = utcnow()
        anteriores = []
        for i in range(5, 0, -1):
            met = Metric(machine_id=machine_id, cpu_percent=cpu, mem_percent=40,
                         timestamp=agora - timedelta(seconds=i * 30))
            db.add(met)
            db.flush()
            db.add(ProcessSnapshot(metric_id=met.id, pid=9, name=proc_name, cpu_percent=cpu,
                                   mem_percent=5.0, mem_rss=1e9, num_threads=8, status="running"))
            anteriores.append(met)
        atual = Metric(machine_id=machine_id, cpu_percent=cpu, mem_percent=40, timestamp=agora)
        db.add(atual)
        db.commit()
        return atual, anteriores

    def test_jogo_assinado_nao_e_diagnosticado_como_travado(self, db):
        from app.services.behavior_analyzer import DetectionContext, detect_cpu_loop
        from app.services import trust
        m = _machine(db)
        atual, anteriores = self._historico(db, m.id, "jogo.exe", 92)
        proc = _proc(name="jogo.exe", exe="C:\\Program Files (x86)\\Steam\\jogo.exe",
                     publisher="Estudio SA", cpu_percent=92.0)
        ctx = DetectionContext(trust_levels=trust.evaluate_all(db, m.id, [proc]))
        r = detect_cpu_loop(atual, [proc], anteriores, db, ctx)
        assert r is not None, "o consumo alto continua sendo registrado"
        assert r.anomaly_type == "high_cpu"
        assert r.severity == "low"

    def test_executavel_desconhecido_continua_sendo_loop(self, db):
        from app.services.behavior_analyzer import DetectionContext, detect_cpu_loop
        from app.services import trust
        m = _machine(db)
        atual, anteriores = self._historico(db, m.id, "runaway.exe", 99)
        proc = _proc(name="runaway.exe", exe="C:\\Users\\v\\Downloads\\runaway.exe",
                     signed="unsigned", publisher=None, cpu_percent=99.0)
        ctx = DetectionContext(trust_levels=trust.evaluate_all(db, m.id, [proc]))
        r = detect_cpu_loop(atual, [proc], anteriores, db, ctx)
        assert r is not None and r.anomaly_type == "cpu_loop"
