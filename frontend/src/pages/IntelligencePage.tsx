import { useAuth } from "@/context/AuthContext";
import { insightApi } from "@/api/endpoints";
import { useAsync } from "@/lib/useAsync";
import { Badge, Disclaimer, EmptyState, ErrorState, Loading, PageHeader } from "@/components/ui";
import { formatCurrency, policyTypeLabel, severityTone } from "@/lib/format";
import type { CoverageNode, IntelligenceItem } from "@/api/types";

const KIND_LABELS: Record<string, string> = {
  expiring: "Expiring",
  missing_info: "Missing information",
  potential_overlap: "Potential overlap",
  action: "Action",
};

export function IntelligencePage() {
  const { activeFamilyId } = useAuth();
  const intel = useAsync(() => insightApi.intelligence(activeFamilyId!), [activeFamilyId]);
  const coverage = useAsync(() => insightApi.coverageMap(activeFamilyId!), [activeFamilyId]);

  if (!activeFamilyId) return null;

  return (
    <div>
      <PageHeader
        title="Insurance Intelligence"
        description="What may be missing, expiring, or overlapping in your family's cover."
      />

      <section className="mb-8">
        <h2 className="mb-3 text-sm font-semibold uppercase tracking-wide text-ink-500">
          Attention items
        </h2>
        {intel.loading ? (
          <Loading />
        ) : intel.error ? (
          <ErrorState message={intel.error} onRetry={intel.reload} />
        ) : intel.data!.items.length === 0 ? (
          <EmptyState
            title="Nothing flagged"
            description="No missing information, upcoming expiries, or overlaps were detected in your recorded policies."
          />
        ) : (
          <ul className="space-y-3">
            {intel.data!.items.map((item: IntelligenceItem, i) => (
              <li key={i} className="card p-4">
                <div className="flex items-start gap-3">
                  <Badge tone={severityTone(item.severity)}>
                    {KIND_LABELS[item.kind] ?? item.kind.replace(/_/g, " ")}
                  </Badge>
                  <div>
                    <p className="text-sm font-medium text-ink-900">{item.title}</p>
                    <p className="mt-0.5 text-sm text-ink-500">{item.detail}</p>
                  </div>
                </div>
              </li>
            ))}
          </ul>
        )}
      </section>

      <section>
        <h2 className="mb-3 text-sm font-semibold uppercase tracking-wide text-ink-500">Coverage map</h2>
        {coverage.loading ? (
          <Loading />
        ) : coverage.error ? (
          <ErrorState message={coverage.error} onRetry={coverage.reload} />
        ) : (
          <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
            {coverage.data!.categories.map((cat: CoverageNode) => (
              <div key={cat.category} className="card p-5">
                <div className="flex items-center justify-between">
                  <h3 className="font-medium text-ink-900">{policyTypeLabel(cat.category)}</h3>
                  <span className="badge-neutral">{cat.policy_count}</span>
                </div>
                <p className="mt-2 text-lg font-semibold text-ink-900">
                  {formatCurrency(cat.total_coverage)}
                </p>
                {cat.policyholders.length > 0 && (
                  <p className="mt-1 text-xs text-ink-500">
                    Covered: {cat.policyholders.join(", ")}
                  </p>
                )}
                {cat.nearest_expiry && (
                  <p className="mt-1 text-xs text-ink-500">
                    Nearest expiry: {cat.nearest_expiry}
                  </p>
                )}
                {cat.missing_info.length > 0 && (
                  <div className="mt-3">
                    <p className="text-xs font-medium text-amber-700">Missing information</p>
                    <ul className="mt-1 list-disc pl-4 text-xs text-ink-500">
                      {cat.missing_info.map((m, i) => <li key={i}>{m}</li>)}
                    </ul>
                  </div>
                )}
                {cat.attention.length > 0 && (
                  <div className="mt-3">
                    <p className="text-xs font-medium text-ink-700">Attention</p>
                    <ul className="mt-1 list-disc pl-4 text-xs text-ink-500">
                      {cat.attention.map((m, i) => <li key={i}>{m}</li>)}
                    </ul>
                  </div>
                )}
              </div>
            ))}
          </div>
        )}
      </section>

      <Disclaimer>
        Overlap findings are described as <em>potential</em> overlaps based on the policies you have
        recorded. They are not a recommendation to cancel cover. Consult your insurer or adviser
        before making coverage decisions.
      </Disclaimer>
    </div>
  );
}
