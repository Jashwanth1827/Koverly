import { createContext, useContext, useEffect, useMemo, useState, type ReactNode } from "react";
import { authApi, familyApi } from "@/api/endpoints";
import { getToken, setToken } from "@/api/client";
import type { Family, FamilyAccess, User } from "@/api/types";

interface AuthState {
  user: User | null;
  loading: boolean;
  families: Family[];
  activeFamilyId: string | null;
  activeAccess: FamilyAccess | null;
  login: (email: string, password: string) => Promise<void>;
  register: (email: string, name: string, password: string) => Promise<void>;
  logout: () => void;
  refreshFamilies: () => Promise<Family[]>;
  setActiveFamily: (id: string | null) => void;
}

const Ctx = createContext<AuthState | null>(null);
const FAMILY_KEY = "koverly.activeFamily";

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<User | null>(null);
  const [loading, setLoading] = useState(true);
  const [families, setFamilies] = useState<Family[]>([]);
  const [activeFamilyId, setActiveFamilyId] = useState<string | null>(
    localStorage.getItem(FAMILY_KEY),
  );
  const [activeAccess, setActiveAccess] = useState<FamilyAccess | null>(null);

  useEffect(() => {
    const token = getToken();
    if (!token) {
      setLoading(false);
      return;
    }
    authApi
      .me()
      .then((u) => {
        setUser(u);
        return familyApi.list();
      })
      .then((fams) => {
        setFamilies(fams);
        if (fams.length && !fams.some((f) => f.id === activeFamilyId)) {
          setActiveFamilyId(fams[0].id);
        }
      })
      .catch(() => {
        setToken(null);
        setUser(null);
      })
      .finally(() => setLoading(false));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    if (!activeFamilyId) {
      setActiveAccess(null);
      localStorage.removeItem(FAMILY_KEY);
      return;
    }
    localStorage.setItem(FAMILY_KEY, activeFamilyId);
    familyApi
      .get(activeFamilyId)
      .then(setActiveAccess)
      .catch(() => setActiveAccess(null));
  }, [activeFamilyId]);

  async function afterAuth(token: string, u: User) {
    setToken(token);
    setUser(u);
    const fams = await familyApi.list();
    setFamilies(fams);
    if (fams.length) setActiveFamilyId(fams[0].id);
  }

  const value = useMemo<AuthState>(
    () => ({
      user,
      loading,
      families,
      activeFamilyId,
      activeAccess,
      async login(email, password) {
        const res = await authApi.login({ email, password });
        await afterAuth(res.access_token, res.user);
      },
      async register(email, name, password) {
        const res = await authApi.register({ email, full_name: name, password });
        await afterAuth(res.access_token, res.user);
      },
      logout() {
        setToken(null);
        setUser(null);
        setFamilies([]);
        setActiveFamilyId(null);
      },
      async refreshFamilies() {
        const fams = await familyApi.list();
        setFamilies(fams);
        // If the active family no longer exists (e.g. it was just deleted),
        // fall back to the first available family or none.
        setActiveFamilyId((current) => {
          if (current && fams.some((f) => f.id === current)) return current;
          return fams.length ? fams[0].id : null;
        });
        return fams;
      },
      setActiveFamily(id) {
        setActiveFamilyId(id);
      },
    }),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [user, loading, families, activeFamilyId, activeAccess],
  );

  return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
}

export function useAuth(): AuthState {
  const ctx = useContext(Ctx);
  if (!ctx) throw new Error("useAuth must be used within AuthProvider");
  return ctx;
}
