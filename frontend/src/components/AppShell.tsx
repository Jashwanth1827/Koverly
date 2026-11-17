import { useEffect, useState } from "react";
import { Link, NavLink, Outlet, useLocation, useNavigate } from "react-router-dom";
import { useAuth } from "@/context/AuthContext";
import { AppFooter } from "@/components/Footer";
import { initials } from "@/lib/format";

const NAV = [
  { to: "/", label: "Dashboard", icon: "▦", end: true },
  { to: "/policies", label: "Policies", icon: "▤" },
  { to: "/family", label: "Family", icon: "◍" },
  { to: "/claims", label: "Claims", icon: "✚" },
  { to: "/intelligence", label: "Insurance Intelligence", icon: "◈" },
  { to: "/documents", label: "Documents", icon: "▥" },
  { to: "/calendar", label: "Calendar", icon: "▦" },
  { to: "/ask", label: "Ask InsuraOS", icon: "✦" },
  { to: "/settings", label: "Settings", icon: "⚙" },
];

const MOBILE_NAV = [
  { to: "/", label: "Home", icon: "▦", end: true },
  { to: "/policies", label: "Policies", icon: "▤" },
  { to: "/documents", label: "Docs", icon: "▥" },
  { to: "/ask", label: "Ask", icon: "✦" },
];

function navClass(isActive: boolean) {
  return `flex items-center gap-3 rounded-lg px-3 py-2 text-sm font-medium transition-colors ${
    isActive ? "bg-brand-50 text-brand-700" : "text-ink-700 hover:bg-slate-100"
  }`;
}

export function AppShell() {
  const { user, families, activeFamilyId, activeAccess, setActiveFamily, logout } = useAuth();
  const navigate = useNavigate();
  const location = useLocation();
  const [menuOpen, setMenuOpen] = useState(false);

  // Close the mobile menu whenever navigation happens, including back/forward.
  useEffect(() => {
    setMenuOpen(false);
  }, [location.pathname, location.search]);

  // Let keyboard and mobile users dismiss the drawer without hunting for the toggle.
  useEffect(() => {
    if (!menuOpen) return;
    function onKeyDown(event: KeyboardEvent) {
      if (event.key === "Escape") setMenuOpen(false);
    }
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [menuOpen]);

  function signOut() {
    logout();
    setMenuOpen(false);
    navigate("/login");
  }

  return (
    <div className="min-h-full lg:flex">
      {/* Sidebar (desktop) */}
      <aside className="hidden w-64 shrink-0 border-r border-slate-200 bg-white lg:flex lg:flex-col">
        <Link to="/" className="flex items-center gap-2 px-5 py-5" aria-label="Koverly home">
          <span className="flex h-8 w-8 items-center justify-center rounded-lg bg-brand-600 text-sm font-bold text-white">
            K
          </span>
          <span className="text-lg font-semibold tracking-tight hover:text-brand-700">Koverly</span>
        </Link>

        <div className="px-3">
          <label htmlFor="family-select" className="label px-2 text-xs uppercase tracking-wide text-ink-300">
            Family
          </label>
          <select
            id="family-select"
            className="input"
            value={activeFamilyId ?? ""}
            onChange={(e) => setActiveFamily(e.target.value || null)}
          >
            {families.length === 0 && <option value="">No family yet</option>}
            {families.map((f) => (
              <option key={f.id} value={f.id}>
                {f.name}
              </option>
            ))}
          </select>
          {activeAccess && (
            <p className="mt-1 px-2 text-xs capitalize text-ink-300">Role: {activeAccess.role}</p>
          )}
        </div>

        <form
          className="px-3 pt-3"
          role="search"
          onSubmit={(e) => {
            e.preventDefault();
            const q = (e.currentTarget.elements.namedItem("q") as HTMLInputElement).value.trim();
            navigate(q ? `/search?q=${encodeURIComponent(q)}` : "/search");
          }}
        >
          <label htmlFor="global-search" className="sr-only">
            Search
          </label>
          <input
            id="global-search"
            name="q"
            type="search"
            className="input"
            placeholder="Search…"
          />
        </form>

        <nav className="mt-4 flex-1 space-y-0.5 overflow-y-auto px-3" aria-label="Main navigation">
          {NAV.map((item) => (
            <NavLink
              key={item.to}
              to={item.to}
              end={item.end}
              className={({ isActive }) => navClass(isActive)}
            >
              <span aria-hidden className="w-4 text-center text-ink-300">
                {item.icon}
              </span>
              {item.label}
            </NavLink>
          ))}
        </nav>

        <div className="border-t border-slate-200 p-3">
          <NavLink to="/emergency" className="btn-danger w-full">
            Emergency
          </NavLink>
          <div className="mt-3 flex items-center gap-3 px-2">
            <span className="flex h-8 w-8 items-center justify-center rounded-full bg-slate-200 text-xs font-semibold text-ink-700">
              {initials(user?.full_name ?? "?")}
            </span>
            <div className="min-w-0 flex-1">
              <p className="truncate text-sm font-medium text-ink-900">{user?.full_name}</p>
              <p className="truncate text-xs text-ink-500">{user?.email}</p>
            </div>
          </div>
          <button className="btn-ghost mt-2 w-full justify-start" onClick={signOut}>
            Sign out
          </button>
        </div>
      </aside>

      {/* Mobile top bar */}
      <div className="flex min-w-0 flex-1 flex-col">
        <header className="flex items-center justify-between border-b border-slate-200 bg-white px-4 py-3 lg:hidden">
          <Link to="/" className="flex items-center gap-2" aria-label="Koverly home">
            <span className="flex h-7 w-7 items-center justify-center rounded-md bg-brand-600 text-xs font-bold text-white">
              K
            </span>
            <span className="font-semibold">Koverly</span>
          </Link>
          <button
            className="btn-ghost px-2"
            onClick={() => setMenuOpen((v) => !v)}
            aria-expanded={menuOpen}
            aria-controls="mobile-menu"
            aria-label={menuOpen ? "Close menu" : "Open menu"}
          >
            {menuOpen ? "✕" : "☰"}
          </button>
        </header>

        {menuOpen && (
          <>
            <button
              type="button"
              aria-label="Close menu"
              className="fixed inset-x-0 bottom-16 top-[53px] z-40 bg-slate-900/30 lg:hidden"
              onClick={() => setMenuOpen(false)}
            />
            <div
              id="mobile-menu"
              role="dialog"
              aria-modal="true"
              aria-label="Navigation menu"
              className="fixed inset-x-0 bottom-16 top-[53px] z-50 overflow-y-auto border-b border-slate-200 bg-white px-4 py-4 shadow-xl lg:hidden"
            >
              <label htmlFor="mobile-family-select" className="label text-xs uppercase tracking-wide text-ink-300">
                Family
              </label>
              <select
                id="mobile-family-select"
                className="input"
                value={activeFamilyId ?? ""}
                onChange={(e) => setActiveFamily(e.target.value || null)}
              >
                {families.length === 0 && <option value="">No family yet</option>}
                {families.map((f) => (
                  <option key={f.id} value={f.id}>
                    {f.name}
                  </option>
                ))}
              </select>

              <form
                className="mt-3"
                role="search"
                onSubmit={(e) => {
                  e.preventDefault();
                  const q = (e.currentTarget.elements.namedItem("q") as HTMLInputElement).value.trim();
                  setMenuOpen(false);
                  navigate(q ? `/search?q=${encodeURIComponent(q)}` : "/search");
                }}
              >
                <label htmlFor="mobile-search" className="sr-only">
                  Search your records
                </label>
                <input id="mobile-search" name="q" type="search" className="input" placeholder="Search…" />
              </form>

              <nav className="mt-3 space-y-0.5" aria-label="Mobile main navigation">
                {NAV.map((item) => (
                  <NavLink
                    key={item.to}
                    to={item.to}
                    end={item.end}
                    className={({ isActive }) => navClass(isActive)}
                    onClick={() => setMenuOpen(false)}
                  >
                    <span aria-hidden className="w-4 text-center text-ink-300">
                      {item.icon}
                    </span>
                    {item.label}
                  </NavLink>
                ))}
              </nav>

              <NavLink
                to="/emergency"
                className="btn-danger mt-3 w-full"
                onClick={() => setMenuOpen(false)}
              >
                Emergency
              </NavLink>
              <button className="btn-ghost mt-1 w-full justify-start" onClick={signOut}>
                Sign out
              </button>
            </div>
          </>
        )}

        <main className="mx-auto flex w-full max-w-6xl min-w-0 flex-1 flex-col px-4 py-6 pb-24 lg:px-8 lg:pb-10">
          <div className="min-w-0 flex-1">
            <Outlet />
          </div>
          <AppFooter withLinks />
        </main>
      </div>

      {/* Mobile bottom nav */}
      <nav
        className="fixed bottom-0 left-0 right-0 z-40 flex border-t border-slate-200 bg-white lg:hidden"
        aria-label="Mobile navigation"
      >
        {MOBILE_NAV.map((item) => (
          <NavLink
            key={item.to}
            to={item.to}
            end={item.end}
            className={({ isActive }) =>
              `flex flex-1 flex-col items-center gap-0.5 py-2 text-[11px] font-medium ${
                isActive ? "text-brand-700" : "text-ink-500"
              }`
            }
          >
            <span aria-hidden className="text-base">
              {item.icon}
            </span>
            {item.label}
          </NavLink>
        ))}
        <button
          type="button"
          className={`flex flex-1 flex-col items-center gap-0.5 py-2 text-[11px] font-medium ${
            menuOpen ? "text-brand-700" : "text-ink-500"
          }`}
          onClick={() => setMenuOpen((v) => !v)}
          aria-expanded={menuOpen}
          aria-controls="mobile-menu"
        >
          <span aria-hidden className="text-base">
            ☰
          </span>
          Menu
        </button>
      </nav>
    </div>
  );
}
