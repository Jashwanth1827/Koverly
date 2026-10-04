import type {
  AskResponse,
  AuditLog,
  CalendarEvent,
  Claim,
  ClaimDetail,
  CoverageMap,
  Dashboard,
  Document,
  EmergencyProfile,
  EmergencyShare,
  Extraction,
  Family,
  FamilyAccess,
  FamilyMember,
  Page,
  Policy,
  PolicySummary,
  PublicConfig,
  Reminder,
  SearchResult,
  Subscription,
} from "./types";
import { api } from "./client";

export const authApi = {
  register: (body: { email: string; full_name: string; password: string; phone?: string }) =>
    api.post<import("./types").TokenResponse>("/auth/register", body),
  login: (body: { email: string; password: string }) =>
    api.post<import("./types").TokenResponse>("/auth/login", body),
  me: () => api.get<import("./types").User>("/auth/me"),
};

export const configApi = {
  get: () => api.get<PublicConfig>("/config"),
};

export const familyApi = {
  list: () => api.get<Family[]>("/families"),
  create: (name: string) => api.post<Family>("/families", { name }),
  get: (id: string) => api.get<FamilyAccess>(`/families/${id}`),
  update: (id: string, name: string) => api.patch<Family>(`/families/${id}`, { name }),
  members: (id: string) => api.get<FamilyMember[]>(`/families/${id}/members`),
  addMember: (id: string, body: Partial<FamilyMember>) =>
    api.post<FamilyMember>(`/families/${id}/members`, body),
  updateMember: (id: string, memberId: string, body: Partial<FamilyMember>) =>
    api.patch<FamilyMember>(`/families/${id}/members/${memberId}`, body),
  removeMember: (id: string, memberId: string) =>
    api.delete<{ message: string }>(`/families/${id}/members/${memberId}`),
  invite: (id: string, email: string, role: string, member_id?: string) =>
    api.post<FamilyMember>(`/families/${id}/invites`, { email, role, member_id }),
  changeRole: (id: string, memberId: string, role: string) =>
    api.patch<FamilyMember>(`/families/${id}/members/${memberId}/role`, { role }),
  remove: (id: string) => api.delete<{ message: string }>(`/families/${id}`),
};

export const policyApi = {
  list: (familyId: string, params: Record<string, string | number> = {}) => {
    const qs = new URLSearchParams(
      Object.entries(params).map(([k, v]) => [k, String(v)]),
    ).toString();
    return api.get<Page<Policy>>(`/families/${familyId}/policies${qs ? `?${qs}` : ""}`);
  },
  get: (familyId: string, id: string) => api.get<Policy>(`/families/${familyId}/policies/${id}`),
  create: (familyId: string, body: Record<string, unknown>) =>
    api.post<Policy>(`/families/${familyId}/policies`, body),
  update: (familyId: string, id: string, body: Record<string, unknown>) =>
    api.patch<Policy>(`/families/${familyId}/policies/${id}`, body),
  remove: (familyId: string, id: string) =>
    api.delete<{ message: string }>(`/families/${familyId}/policies/${id}`),
  summary: (familyId: string) => api.get<PolicySummary>(`/families/${familyId}/policies/summary`),
  /** Generated (never raw) PDF summary of a single policy. */
  summaryPdfBlob: (familyId: string, id: string) =>
    api.blob(`/families/${familyId}/policies/${id}/summary.pdf`),
};

export const documentApi = {
  list: (familyId: string, params: Record<string, string | number> = {}) => {
    const qs = new URLSearchParams(
      Object.entries(params).map(([k, v]) => [k, String(v)]),
    ).toString();
    return api.get<Page<Document>>(`/families/${familyId}/documents${qs ? `?${qs}` : ""}`);
  },
  upload: (familyId: string, file: File, params: Record<string, string> = {}) => {
    const qs = new URLSearchParams(params).toString();
    return api.upload<Document>(`/families/${familyId}/documents${qs ? `?${qs}` : ""}`, file);
  },
  remove: (familyId: string, id: string) =>
    api.delete<{ message: string }>(`/families/${familyId}/documents/${id}`),
  reprocess: (familyId: string, id: string) =>
    api.post<Document>(`/families/${familyId}/documents/${id}/reprocess`),
  extractions: (familyId: string, id: string) =>
    api.get<Extraction[]>(`/families/${familyId}/documents/${id}/extractions`),
  confirm: (
    familyId: string,
    id: string,
    body: { policy_id?: string; confirm: Record<string, string>; reject: string[] },
  ) => api.post<Extraction[]>(`/families/${familyId}/documents/${id}/extractions/confirm`, body),
  signedUrl: (familyId: string, id: string, disposition: "inline" | "attachment" = "inline") =>
    api.post<{ url: string; expires_in: number }>(
      `/families/${familyId}/documents/${id}/signed-url?disposition=${disposition}`,
    ),
  downloadUrl: (familyId: string, id: string) =>
    `/api/v1/families/${familyId}/documents/${id}/download`,
  /** Authenticated binary fetch (never exposes the raw file in a URL). */
  previewBlob: (familyId: string, id: string) =>
    api.blob(`/families/${familyId}/documents/${id}/download`),
};

export const claimApi = {
  list: (familyId: string, params: Record<string, string | number> = {}) => {
    const qs = new URLSearchParams(
      Object.entries(params).map(([k, v]) => [k, String(v)]),
    ).toString();
    return api.get<Page<Claim>>(`/families/${familyId}/claims${qs ? `?${qs}` : ""}`);
  },
  get: (familyId: string, id: string) => api.get<ClaimDetail>(`/families/${familyId}/claims/${id}`),
  create: (familyId: string, body: Record<string, unknown>) =>
    api.post<Claim>(`/families/${familyId}/claims`, body),
  update: (familyId: string, id: string, body: Record<string, unknown>) =>
    api.patch<Claim>(`/families/${familyId}/claims/${id}`, body),
  remove: (familyId: string, id: string) =>
    api.delete<{ message: string }>(`/families/${familyId}/claims/${id}`),
  documents: (familyId: string, id: string) =>
    api.get<Document[]>(`/families/${familyId}/claims/${id}/documents`),
  uploadDocument: (familyId: string, id: string, file: File) =>
    api.upload<Document>(`/families/${familyId}/claims/${id}/documents`, file),
};

export const insightApi = {
  dashboard: (familyId: string) => api.get<Dashboard>(`/families/${familyId}/dashboard`),
  intelligence: (familyId: string) =>
    api.get<{ items: import("./types").IntelligenceItem[] }>(
      `/families/${familyId}/insurance-intelligence`,
    ),
  coverageMap: (familyId: string) => api.get<CoverageMap>(`/families/${familyId}/coverage-map`),
  calendar: (familyId: string, start?: string, end?: string) => {
    const qs = new URLSearchParams();
    if (start) qs.set("start", start);
    if (end) qs.set("end", end);
    return api.get<CalendarEvent[]>(`/families/${familyId}/calendar?${qs}`);
  },
  search: (familyId: string, q: string) =>
    api.get<{ query: string; results: SearchResult[] }>(
      `/families/${familyId}/search?q=${encodeURIComponent(q)}`,
    ),
  ask: (familyId: string, question: string, policyId?: string) =>
    api.post<AskResponse>("/assistant/ask", {
      family_id: familyId,
      question,
      policy_id: policyId,
    }),
  reminders: (familyId: string) =>
    api.get<Page<Reminder>>(`/families/${familyId}/reminders`),
  createReminder: (familyId: string, body: Record<string, unknown>) =>
    api.post<Reminder>(`/families/${familyId}/reminders`, body),
  acknowledgeReminder: (familyId: string, id: string) =>
    api.post<Reminder>(`/families/${familyId}/reminders/${id}/acknowledge`),
  completeReminder: (familyId: string, id: string) =>
    api.post<Reminder>(`/families/${familyId}/reminders/${id}/complete`),
  auditLogs: (familyId: string) =>
    api.get<Page<AuditLog>>(`/families/${familyId}/audit-logs`),
  subscription: (familyId: string) =>
    api.get<Subscription>(`/families/${familyId}/subscription`),
  setSubscription: (familyId: string, plan: string) =>
    api.patch<Subscription>(`/families/${familyId}/subscription`, { plan }),
};

export const emergencyApi = {
  profile: (familyId: string, memberId?: string) =>
    api.get<EmergencyProfile>(
      `/families/${familyId}/emergency${memberId ? `?member_id=${memberId}` : ""}`,
    ),
  createShare: (familyId: string, body: { member_id?: string; ttl_minutes: number }) =>
    api.post<EmergencyShare>(`/families/${familyId}/emergency/shares`, body),
  revokeShare: (familyId: string, shareId: string) =>
    api.delete<{ message: string }>(`/families/${familyId}/emergency/shares/${shareId}`),
  resolve: (token: string) => api.get<EmergencyProfile>(`/emergency/share/${token}`),
};
