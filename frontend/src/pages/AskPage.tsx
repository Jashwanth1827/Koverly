import { useRef, useState } from "react";
import { Link } from "react-router-dom";
import { useAuth } from "@/context/AuthContext";
import { insightApi } from "@/api/endpoints";
import { ApiError } from "@/api/client";
import { Disclaimer, PageHeader } from "@/components/ui";
import type { AskResponse, RecordMatch } from "@/api/types";

interface Turn {
  question: string;
  response?: AskResponse;
  error?: string;
}

const MATCH_LABEL: Record<string, string> = {
  policy: "Policy",
  family_member: "Family member",
  claim: "Claim",
  document: "Document",
};

function matchHref(m: RecordMatch): string {
  switch (m.kind) {
    case "policy":
      return `/policies/${m.id}`;
    case "claim":
      return `/claims/${m.id}`;
    case "family_member":
      return "/family";
    case "document":
      return "/documents";
    default:
      return "/intelligence";
  }
}

const SUGGESTIONS = [
  "How much health insurance does my family have?",
  "Which policies expire this year?",
  "What insurance does my father have?",
  "Which policy covers hospitalisation?",
  "What are the waiting periods?",
  "What claims are currently active?",
];

export function AskPage() {
  const { activeFamilyId } = useAuth();
  const [question, setQuestion] = useState("");
  const [turns, setTurns] = useState<Turn[]>([]);
  const [busy, setBusy] = useState(false);
  const bottomRef = useRef<HTMLDivElement>(null);

  async function ask(q: string) {
    if (!q.trim() || !activeFamilyId) return;
    setBusy(true);
    setQuestion("");
    const idx = turns.length;
    setTurns((t) => [...t, { question: q }]);
    try {
      const response = await insightApi.ask(activeFamilyId, q);
      setTurns((t) => t.map((turn, i) => (i === idx ? { ...turn, response } : turn)));
    } catch (err) {
      setTurns((t) =>
        t.map((turn, i) =>
          i === idx
            ? { ...turn, error: err instanceof ApiError ? err.message : "Could not answer that." }
            : turn,
        ),
      );
    } finally {
      setBusy(false);
      setTimeout(() => bottomRef.current?.scrollIntoView({ behavior: "smooth" }), 50);
    }
  }

  return (
    <div>
      <PageHeader
        title="Ask InsuraOS"
        description="Ask about your own policies, family, and claims. Answers are grounded in your records and documents."
      />

      {turns.length === 0 ? (
        <div className="card p-6">
          <p className="text-sm text-ink-500">Try one of these:</p>
          <div className="mt-3 flex flex-wrap gap-2">
            {SUGGESTIONS.map((s) => (
              <button key={s} className="btn-secondary text-left text-sm" onClick={() => ask(s)}>
                {s}
              </button>
            ))}
          </div>
        </div>
      ) : (
        <div className="space-y-6">
          {turns.map((turn, i) => (
            <div key={i} className="space-y-3">
              <div className="flex justify-end">
                <p className="max-w-[80%] rounded-2xl rounded-br-sm bg-brand-600 px-4 py-2 text-sm text-white">
                  {turn.question}
                </p>
              </div>
              <div className="flex justify-start">
                <div className="max-w-[90%] rounded-2xl rounded-bl-sm border border-slate-200 bg-white px-4 py-3">
                  {turn.error ? (
                    <p className="text-sm text-red-700">{turn.error}</p>
                  ) : turn.response ? (
                    <>
                      <p className="whitespace-pre-wrap text-sm text-ink-900">{turn.response.answer}</p>

                      {turn.response.matches.length > 0 && (
                        <div className="mt-3 border-t border-slate-100 pt-3">
                          <p className="text-xs font-medium uppercase tracking-wide text-ink-500">
                            Matching records
                          </p>
                          <ul className="mt-1 space-y-1">
                            {turn.response.matches.map((m) => (
                              <li key={`${m.kind}-${m.id}`}>
                                <Link
                                  to={matchHref(m)}
                                  className="flex items-center justify-between gap-3 rounded-md px-2 py-1.5 text-xs text-ink-700 hover:bg-slate-50"
                                >
                                  <span className="min-w-0">
                                    <span className="block truncate font-medium text-ink-900">
                                      {m.title}
                                    </span>
                                    {m.subtitle && (
                                      <span className="block truncate text-ink-500">{m.subtitle}</span>
                                    )}
                                  </span>
                                  <span className="badge-neutral shrink-0">
                                    {MATCH_LABEL[m.kind] ?? m.kind}
                                  </span>
                                </Link>
                              </li>
                            ))}
                          </ul>
                        </div>
                      )}

                      {turn.response.sources.length > 0 && (
                        <div className="mt-3 border-t border-slate-100 pt-3">
                          <p className="text-xs font-medium uppercase tracking-wide text-ink-500">Sources</p>
                          <ul className="mt-1 space-y-1">
                            {turn.response.sources.map((s, si) => (
                              <li key={si} className="text-xs text-ink-500">
                                {s.label || `${s.document_name} — page ${s.page_number ?? "?"}`}
                                {s.snippet && (
                                  <span className="block italic text-ink-300">“{s.snippet.slice(0, 160)}”</span>
                                )}
                              </li>
                            ))}
                          </ul>
                        </div>
                      )}

                      {!turn.response.grounded && (
                        <p className="mt-2 text-xs text-ink-300">
                          No matching information was found in your records.
                        </p>
                      )}

                      <p className="mt-3 text-xs text-ink-300">{turn.response.disclaimer}</p>
                    </>
                  ) : (
                    <p className="text-sm text-ink-500">Thinking…</p>
                  )}
                </div>
              </div>
            </div>
          ))}
          <div ref={bottomRef} />
        </div>
      )}

      <form
        className="sticky bottom-16 mt-6 flex gap-2 lg:bottom-4"
        onSubmit={(e) => {
          e.preventDefault();
          ask(question);
        }}
      >
        <input
          className="input"
          placeholder="Ask about your insurance…"
          value={question}
          onChange={(e) => setQuestion(e.target.value)}
          aria-label="Your question"
        />
        <button className="btn-primary" disabled={busy || !question.trim()}>
          {busy ? "…" : "Ask"}
        </button>
      </form>

      <Disclaimer>
        Answers are generated from the policies and documents you have recorded. Always confirm
        important details against the original policy document. Koverly is not an insurer, lawyer, or
        financial adviser. <Link to="/intelligence" className="underline">See what may be missing</Link>.
      </Disclaimer>
    </div>
  );
}
