import { Link } from "react-router-dom";
import { AppFooter } from "@/components/Footer";
import { usePageMeta } from "@/lib/pageMeta";

export function NotFoundPage() {
  usePageMeta("Page not found", "The page you were looking for could not be found.");

  return (
    <div className="mx-auto flex min-h-full w-full max-w-xl flex-col justify-center px-4 py-16">
      <div className="card p-6 text-center sm:p-10">
        <p className="text-5xl font-bold tracking-tight text-brand-600">404</p>
        <h1 className="mt-3 text-xl font-semibold text-ink-900">We couldn't find that page</h1>
        <p className="mt-2 text-sm text-ink-500">
          The link may be out of date, or the page may have moved. You can head back to your
          dashboard or search your records instead.
        </p>
        <div className="mt-6 flex flex-wrap justify-center gap-3">
          <Link to="/" className="btn-primary">
            Go to dashboard
          </Link>
          <Link to="/search" className="btn-secondary">
            Search records
          </Link>
        </div>
      </div>
      <AppFooter />
    </div>
  );
}
