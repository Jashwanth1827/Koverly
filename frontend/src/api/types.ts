/* Domain types mirroring the backend API schemas. */

export type FamilyRole = "owner" | "admin" | "member" | "viewer";

export interface User {
  id: string;
  email: string;
  full_name: string;
  phone: string | null;
  is_active: boolean;
  created_at: string;
}

export interface TokenResponse {
  access_token: string;
  token_type: string;
  user: User;
}

export interface Family {
  id: string;
  name: string;
  owner_user_id: string;
  created_at: string;
}

export interface FamilyAccess {
  family: Family;
  role: FamilyRole;
  member_id: string | null;
}

export interface FamilyMember {
  id: string;
  family_id: string;
  user_id: string | null;
  name: string;
  relationship: string;
  date_of_birth: string | null;
  phone: string | null;
  email: string | null;
  blood_group: string | null;
  role: string;
  is_account_linked: boolean;
  created_at: string;
}

export type PolicyType =
  | "life"
  | "health"
  | "motor"
  | "home"
  | "travel"
  | "personal_accident"
  | "other";

export interface Policy {
  id: string;
  family_id: string;
  member_id: string | null;
  created_by_user_id: string;
  policy_type: PolicyType;
  insurer: string;
  policy_number: string;
  policyholder_name: string | null;
  premium: string | null;
  premium_frequency: string | null;
  sum_insured: string | null;
  start_date: string | null;
  expiry_date: string | null;
  renewal_date: string | null;
  maturity_date: string | null;
  nominee: string | null;
  status: string;
  notes: string | null;
  metadata_json: Record<string, unknown>;
  created_at: string;
  updated_at: string;
}

export interface PolicySummary {
  active_policies: number;
  total_annual_premium: string;
  total_life_coverage: string;
  total_health_coverage: string;
  total_other_coverage: string;
  currency: string;
  by_type: Record<string, number>;
}

export interface Document {
  id: string;
  family_id: string;
  policy_id: string | null;
  claim_id: string | null;
  original_filename: string;
  content_type: string;
  size_bytes: number;
  document_type: string;
  status: "uploaded" | "processing" | "processed" | "failed";
  processing_error: string | null;
  page_count: number | null;
  created_at: string;
  updated_at: string;
}

export interface Extraction {
  id: string;
  document_id: string;
  policy_id: string | null;
  field_name: string;
  value: string | null;
  confidence: number;
  source_page: number | null;
  found: boolean;
  status: "proposed" | "confirmed" | "rejected";
  created_at: string;
}

/** How a document was read: native text, OCR of a scan, or an image. */
export type SourceKind = "text_document" | "scanned_document" | "image_document";

export type Evidence =
  | "explicitly_found"
  | "inferred"
  | "uncertain"
  | "not_found";

export interface DocumentAnalysis {
  id: string;
  document_id: string;
  document_class: string;
  document_class_confidence: number;
  source_kind: SourceKind;
  is_insurance: boolean;
  message: string | null;
  summary: string | null;
  provider: string;
  page_count: number | null;
  ocr_used: boolean;
  created_at: string;
}

export interface CandidateField {
  id: string;
  field_name: string;
  value: string | null;
  confidence: number;
  source_page: number | null;
  source_text: string | null;
  evidence: Evidence;
  review_status: string;
}

export interface PolicyCandidate {
  id: string;
  document_id: string;
  candidate_index: number;
  document_class: string;
  category: string;
  category_confidence: number;
  policy_type: string;
  policy_type_confidence: number;
  policy_subtype: string | null;
  policy_subtype_confidence: number;
  page_start: number | null;
  page_end: number | null;
  category_data: Record<string, string>;
  status: string;
  policy_id: string | null;
  fields: CandidateField[];
}

export interface AnalysisDetail {
  analysis: DocumentAnalysis | null;
  candidates: PolicyCandidate[];
  candidate_count: number;
}

export type ClaimStatus =
  | "draft"
  | "submitted"
  | "documents_required"
  | "under_review"
  | "approved"
  | "rejected"
  | "settled"
  | "closed";

export interface Claim {
  id: string;
  family_id: string;
  policy_id: string;
  member_id: string | null;
  claim_type: string;
  claim_amount: string | null;
  approved_amount: string | null;
  provider: string | null;
  incident_date: string | null;
  submission_date: string | null;
  status: ClaimStatus;
  description: string | null;
  notes: string | null;
  metadata_json: Record<string, unknown>;
  created_at: string;
  updated_at: string;
}

export interface ClaimEvent {
  id: string;
  status: string;
  note: string | null;
  actor_user_id: string | null;
  created_at: string;
}

export interface ClaimDetail extends Claim {
  events: ClaimEvent[];
}

export interface Reminder {
  id: string;
  family_id: string;
  policy_id: string | null;
  claim_id: string | null;
  reminder_type: string;
  title: string;
  due_date: string;
  offsets: number[];
  status: string;
  last_triggered_at: string | null;
  acknowledged_at: string | null;
  completed_at: string | null;
  created_at: string;
}

export interface IntelligenceItem {
  kind: string;
  severity: "info" | "warning" | "critical";
  title: string;
  detail: string;
  policy_id: string | null;
  member_id: string | null;
  due_date: string | null;
}

export interface CoverageNode {
  category: string;
  policy_count: number;
  total_coverage: string;
  policyholders: string[];
  nearest_expiry: string | null;
  missing_info: string[];
  attention: string[];
}

export interface CoverageMap {
  family_id: string;
  categories: CoverageNode[];
}

export interface Dashboard {
  family_id: string;
  family_name: string;
  active_policies: number;
  total_annual_premium: string;
  total_life_coverage: string;
  total_health_coverage: string;
  total_other_coverage: string;
  upcoming_renewals: IntelligenceItem[];
  pending_actions: IntelligenceItem[];
  recent_claims: Claim[];
  alerts: IntelligenceItem[];
  by_type: Record<string, number>;
}

export interface Source {
  document_id: string;
  document_name: string;
  page_number: number | null;
  snippet: string;
  label: string;
}

export interface RecordMatch {
  kind: string;
  id: string;
  title: string;
  subtitle: string | null;
}

export interface AskResponse {
  answer: string;
  sources: Source[];
  grounded: boolean;
  provider: string;
  disclaimer: string;
  matches: RecordMatch[];
}

export interface CalendarEvent {
  id: string;
  kind: string;
  title: string;
  date: string;
  policy_id: string | null;
  claim_id: string | null;
  status: string | null;
}

export interface EmergencyPolicy {
  policy_id: string;
  policy_type: string;
  insurer: string;
  policy_number: string;
  sum_insured: string | null;
  tpa: string | null;
  claim_contact: string | null;
  expiry_date: string | null;
  document_ids: string[];
}

export interface EmergencyProfile {
  family_id: string;
  family_name: string;
  generated_at: string;
  member: {
    id: string;
    name: string;
    relationship: string;
    blood_group: string | null;
    date_of_birth: string | null;
  } | null;
  policies: EmergencyPolicy[];
  contacts: { label: string; value: string }[];
  claim_instructions: string[];
}

export interface EmergencyShare {
  id: string;
  token: string;
  url: string;
  expires_at: string;
  max_views: number;
  view_count: number;
}

export interface AuditLog {
  id: string;
  actor_user_id: string | null;
  family_id: string | null;
  action: string;
  resource_type: string;
  resource_id: string | null;
  metadata_json: Record<string, unknown>;
  created_at: string;
}

export interface Subscription {
  id: string;
  family_id: string;
  plan: "free" | "pro" | "family_pro";
  status: string;
  provider: string | null;
  current_period_end: string | null;
}

export interface SearchResult {
  kind: string;
  id: string;
  title: string;
  subtitle: string | null;
  policy_id: string | null;
}

export interface Page<T> {
  items: T[];
  total: number;
  page: number;
  page_size: number;
}

export interface PublicConfig {
  app_name: string;
  ai_provider: string;
  notification_backend: string;
  storage_backend: string;
  max_upload_mb: number;
  allowed_upload_types: string[];
}
