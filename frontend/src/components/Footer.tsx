import { Link } from "react-router-dom";

const FOOTER_LINKS = [
  { to: "/", label: "Dashboard" },
  { to: "/policies", label: "Policies" },
  { to: "/family", label: "Family" },
  { to: "/claims", label: "Claims" },
  { to: "/documents", label: "Documents" },
  { to: "/calendar", label: "Calendar" },
  { to: "/ask", label: "Ask" },
  { to: "/emergency", label: "Emergency" },
];

/** Footer for every screen. Links are only shown inside the signed-in shell,
 * so they never bounce a visitor back to the login page. */
export function AppFooter({ withLinks = false }: { withLinks?: boolean }) {
  return (
    <footer className="mt-auto w-full border-t border-slate-200 pt-5 text-xs text-ink-500">
      {withLinks && (
        <nav aria-label="Footer navigation" className="flex flex-wrap gap-x-4 gap-y-2">
          {FOOTER_LINKS.map((link) => (
            <Link key={link.to} to={link.to} className="rounded py-1 hover:text-brand-700">
              {link.label}
            </Link>
          ))}
        </nav>
      )}
      <p className="mt-3 leading-relaxed text-ink-300">
        © {new Date().getFullYear()} Koverly · An organizational and informational tool, not an
        insurer or financial adviser.
      </p>
    </footer>
  );
}
