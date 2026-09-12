import { useEffect, useRef, useState } from "react";
import { chatApi, machinesApi, errorMessage } from "../services/api";
import { ChatMessage, Machine } from "../types";
import { PageHeader } from "../components/ui/Layout";
import { Button } from "../components/ui/Button";
import { useToast } from "../components/ui/Toast";
import { Disclosure } from "../components/ui/Disclosure";
import { Send } from "lucide-react";

/**
 * "Pergunte ao seu computador."
 *
 * Conversa em português sobre o histórico. A IA não recebe tudo de uma vez —
 * ela consulta os dados por ferramentas, e o rastro dessas consultas fica
 * disponível para quem quiser ver de onde veio a resposta.
 */
export function Chat() {
  const toast = useToast();
  const [machines, setMachines] = useState<Machine[]>([]);
  const [machineId, setMachineId] = useState<number | undefined>();
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [conversationId, setConversationId] = useState<string | undefined>();
  const [input, setInput] = useState("");
  const [suggestions, setSuggestions] = useState<string[]>([]);
  const [sending, setSending] = useState(false);
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const bottomRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    machinesApi.list().then((r) => setMachines(r.data)).catch(() => {});
  }, []);
  useEffect(() => {
    chatApi.suggestions(machineId).then((r) => setSuggestions(r.data.suggestions)).catch(() => {});
  }, [machineId]);
  useEffect(() => () => { if (pollRef.current) clearInterval(pollRef.current); }, []);
  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages]);

  const send = async (question: string) => {
    if (!question.trim() || sending) return;
    setSending(true);
    const optimistic: ChatMessage = {
      id: -Date.now(), role: "user", content: question, status: "done", created_at: new Date().toISOString(),
      conversation_id: conversationId ?? "", machine_id: machineId,
    };
    setMessages((prev) => [...prev, optimistic]);
    setInput("");
    try {
      const res = await chatApi.ask(question, machineId, conversationId);
      setConversationId(res.data.conversation_id);
      const assistant: ChatMessage = res.data.message;
      setMessages((prev) => [...prev, assistant]);
      pollRef.current = setInterval(async () => {
        try {
          const r = await chatApi.message(assistant.id);
          if (r.data.status !== "pending") {
            if (pollRef.current) clearInterval(pollRef.current);
            setMessages((prev) => prev.map((m) => (m.id === assistant.id ? r.data : m)));
            setSending(false);
          }
        } catch {
          /* continua */
        }
      }, 2500);
    } catch (err) {
      toast.error(errorMessage(err));
      setSending(false);
    }
  };

  return (
    <div className="mx-auto flex h-[calc(100vh-8rem)] max-w-3xl flex-col">
      <PageHeader
        title="Pergunte ao seu computador"
        description="Pergunte em português sobre o histórico — por que ficou lento, o que mudou, o que consome mais."
        aside={
          machines.length > 0 ? (
            <select
              value={machineId ?? ""}
              onChange={(e) => setMachineId(e.target.value ? Number(e.target.value) : undefined)}
              className="h-8 rounded-control border border-edge bg-surface px-2 text-sm text-fg focus:border-accent"
            >
              <option value="">Todos os computadores</option>
              {machines.map((m) => (
                <option key={m.id} value={m.id}>{m.name}</option>
              ))}
            </select>
          ) : undefined
        }
      />

      <div className="mt-4 flex-1 space-y-4 overflow-y-auto pr-1">
        {messages.length === 0 && (
          <div className="space-y-3 pt-6">
            <p className="text-sm text-fg-3">Experimente perguntar:</p>
            <div className="flex flex-col items-start gap-2">
              {suggestions.map((s) => (
                <button
                  key={s}
                  type="button"
                  onClick={() => send(s)}
                  className="rounded-control border border-hairline bg-surface px-3 py-2 text-left text-sm text-fg-2 transition-colors hover:border-edge hover:text-fg"
                >
                  {s}
                </button>
              ))}
            </div>
          </div>
        )}

        {messages.map((m) => (
          <div key={m.id} className={m.role === "user" ? "flex justify-end" : ""}>
            <div className={m.role === "user" ? "max-w-[85%] rounded-panel bg-raised px-4 py-2.5" : "max-w-[92%]"}>
              {m.role === "assistant" && m.status === "pending" ? (
                <p className="flex items-center gap-2 text-sm text-fg-3">
                  <span className="h-3.5 w-3.5 animate-spin rounded-full border-2 border-edge border-t-fg-3" />
                  Consultando os dados…
                </p>
              ) : (
                <p className={`whitespace-pre-line text-sm leading-relaxed ${m.role === "user" ? "text-fg" : "text-fg-2"}`}>
                  {m.content}
                </p>
              )}
              {m.role === "assistant" && m.tool_trace && m.tool_trace.length > 0 && (
                <div className="mt-2">
                  <Disclosure title="Como cheguei nisso" note={`${m.tool_trace.length} consulta(s) aos dados`}>
                    <ul className="space-y-1.5">
                      {m.tool_trace.map((t, i) => (
                        <li key={i} className="font-mono text-micro text-fg-3">
                          {t.tool}({Object.keys(t.args || {}).length ? JSON.stringify(t.args) : ""})
                        </li>
                      ))}
                    </ul>
                    {m.model_used && <p className="mt-2 text-micro text-fg-3">via {m.model_used}</p>}
                  </Disclosure>
                </div>
              )}
            </div>
          </div>
        ))}
        <div ref={bottomRef} />
      </div>

      <form
        onSubmit={(e) => {
          e.preventDefault();
          send(input);
        }}
        className="mt-3 flex items-center gap-2 border-t border-hairline pt-3"
      >
        <input
          value={input}
          onChange={(e) => setInput(e.target.value)}
          placeholder="Escreva sua pergunta…"
          className="h-10 flex-1 rounded-control border border-edge bg-surface px-3 text-sm text-fg placeholder:text-fg-3 focus:border-accent"
        />
        <Button variant="primary" type="submit" disabled={!input.trim() || sending} icon={<Send size={14} aria-hidden="true" />}>
          Enviar
        </Button>
      </form>
    </div>
  );
}
