import { useNavigate } from "react-router-dom";
import { format } from "date-fns";
import { ptBR } from "date-fns/locale";
import { useAuth } from "../context/AuthContext";
import { useTheme } from "../context/ThemeContext";
import { useConfirm } from "../components/ui/ConfirmDialog";
import { PageHeader, Section, Panel, DataList, DataRow } from "../components/ui/Layout";
import { Button } from "../components/ui/Button";
import { GLOSSARY } from "../lib/glossary";

/** Termos do glossário reunidos numa página só, na ordem em que aparecem no painel. */
const GLOSSARY_ORDER: { term: keyof typeof GLOSSARY; label: string }[] = [
  { term: "cpu", label: "Processador" },
  { term: "memoria", label: "Memória" },
  { term: "disco", label: "Disco" },
  { term: "swap", label: "Memória virtual" },
  { term: "temperatura", label: "Temperatura" },
  { term: "load", label: "Fila do processador" },
  { term: "conexoes", label: "Conexões abertas" },
  { term: "gpu", label: "Placa de vídeo" },
  { term: "vram", label: "Memória de vídeo" },
  { term: "saude_bateria", label: "Saúde da bateria" },
  { term: "aprendizado", label: "Aprendizado do sistema" },
  { term: "score", label: "Desvio do padrão" },
  { term: "agent_token", label: "Identificação do computador" },
];

export function Account() {
  const { user, logout } = useAuth();
  const { theme, toggle } = useTheme();
  const confirm = useConfirm();
  const navigate = useNavigate();

  const handleLogout = async () => {
    const ok = await confirm({
      title: "Sair da conta?",
      body: "Seus computadores continuam sendo monitorados. Você só precisará entrar de novo para ver o painel.",
      confirmLabel: "Sair da conta",
    });
    if (!ok) return;
    logout();
    navigate("/login");
  };

  return (
    <div className="max-w-2xl space-y-8">
      <PageHeader title="Sua conta" description="Dados de acesso, aparência do painel e glossário." />

      <Section title="Identificação">
        <Panel className="px-4 py-2">
          <DataList>
            <DataRow label="Usuário" value={user?.username ?? "--"} />
            <DataRow label="E-mail" value={user?.email ?? "--"} />
            {user?.created_at && (
              <DataRow label="Conta criada em" value={format(new Date(user.created_at), "dd/MM/yyyy", { locale: ptBR })} />
            )}
          </DataList>
        </Panel>
        <p className="mt-2 text-xs text-fg-3">A troca de senha pelo painel ainda não está disponível.</p>
      </Section>

      <Section title="Aparência">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <p className="max-w-prose text-sm text-fg-2">
            O tema escuro é o padrão. O claro costuma ler melhor em ambientes iluminados.
          </p>
          <Button variant="secondary" onClick={toggle}>
            Usar tema {theme === "dark" ? "claro" : "escuro"}
          </Button>
        </div>
      </Section>

      <Section title="O que cada medida significa" description="Os mesmos textos dos “?” do painel, reunidos aqui">
        <DataList className="divide-y divide-hairline">
          {GLOSSARY_ORDER.map(({ term, label }) => (
            <div key={term} className="py-3">
              <dt className="text-sm font-medium text-fg">{label}</dt>
              <dd className="mt-1 max-w-prose text-sm leading-relaxed text-fg-2">{GLOSSARY[term]}</dd>
            </div>
          ))}
        </DataList>
      </Section>

      <Section title="Sessão">
        <Button variant="danger" onClick={handleLogout}>
          Sair da conta
        </Button>
      </Section>
    </div>
  );
}
