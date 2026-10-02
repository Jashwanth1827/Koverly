import { useEffect, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { useAuth } from "@/context/AuthContext";
import { insightApi } from "@/api/endpoints";
import { useAsync } from "@/lib/useAsync";
import { EmptyState, ErrorState, Loading, PageHeader } from "@/components/ui";
import type { SearchResult } from "@/api/types";

const KIND_LABEL: Record<string, string> = {
  policy: "Policy",
  family_member: "Family member",
  claim: "Claim",
  document: "Document",
};

function resultHref(r: SearchResult): string {
  switch (r.kind) {
    case "policy":
      return `/policies/${r.id}`;
    case "claim":
      return `/claims/${r.id}`;
    case "family_member":
      return "/family";
    case "document":
      return "/documents";
    default:
      return "/intelligence";
  }
}

export function SearchPage() {
  const { activeFamilyId } = useAuth();
  const [params, setParams] = useSearchParams();
  const initial = params.get("q") ?? "";
  const [term, setTerm] = useState(initial);
  const query = initial.trim();

  useEffect(() => {
    setTerm(params.get("q") ?? "");
  }, [params]);

  const results = useAsync(
    () => (query ? insightApi.search(activeFamilyId!, query) : Promise.resolve(null)),
    [activeFamilyId, query],
  );

  if (!activeFamilyId) return null;

  function submit(e: React.FormEvent) {
    e.preventDefault();
    const next = new URLSearchParams();
    if (term.trim()) next.set("q", term.trim());
    setParams(next);
  }

  return (
    <div>
      <PageHeader
        title="Search"
        description="Find policies, family members, claims, and documents you have recorded."
      />

      <form onSubmit={submit} className="mb-6 flex gap-2" role="search">
        <input
          className="input"
          value={term}
          onChange={(e) => setTerm(e.target.value)}
          placeholder="Search policy numbers, insurers, names…"
          aria-label="Search your insurance records"
          autoFocus
        />
        <button className="btn-primary shrink-0">Search</button>
      </form>

      {!query ? (
        <EmptyState
          title="Search your records"
          description="Enter a policy number, insurer, family member, claim, or document name."
        />
      ) : results.loading ? (
        <Loading />
      ) : results.error ? (
        <ErrorState message={results.error} onRetry={results.reload} />
      ) : !results.data || results.data.results.length === 0 ? (
        <EmptyState
          title="No matches"
          description={`Nothing in this family's records matched “${query}”.`}
        />
      ) : (
        <ul className="space-y-2">
          {results.data.results.map((r) => (
            <li key={`${r.kind}-${r.id}`}>
              <Link
                to={resultHref(r)}
                className="card flex items-center justify-between gap-3 p-3 hover:bg-slate-50"
              >
                <div className="min-w-0">
                  <p className="truncate text-sm font-medium text-ink-900">{r.title}</p>
                  {r.subtitle && <p className="truncate text-xs text-ink-500">{r.subtitle}</p>}
                </div>
                <span className="badge-neutral shrink-0">{KIND_LABEL[r.kind] ?? r.kind}</span>
              </Link>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
