// Types mirror overturn/api/views.py. The interface renders what the engine computed;
// it never recomputes a status, a gap or a deadline itself.

export type Pressure = "none" | "info" | "elevated" | "urgent" | "critical" | "expired";

export type FactStatus =
  | "extracted"
  | "human_verified"
  | "human_answered"
  | "missing"
  | "conflicted"
  | "regime_default"
  | "not_applicable"
  | "not_looked_for";

export interface Provenance {
  doc_id: string;
  page: number;
  char_span: [number, number];
  quote: string | null;
}

export interface Fact {
  field: string;
  kind: "string" | "date" | "bool" | "int" | "string_list";
  origin: "document" | "engine" | "human";
  critical: boolean;
  pii: boolean;
  description: string;
  required: boolean;
  status: FactStatus;
  value: unknown;
  confidence: number | null;
  provenance: Provenance | null;
  reason: string | null;
  regime?: string | null;
  verified_by: string | null;
  recorded_by: string | null;
  conflict: { reads: unknown; provenance: Provenance | null }[];
  packet_ready: boolean;
}

export interface Deadline {
  field: string;
  due: string;
  basis: "stated_in_letter" | "regime_default";
  regime: string | null;
  rule: string;
  anchor_field: string;
  anchor_date: string;
  anchor_is_estimated: boolean;
  days_remaining: number;
  pressure: Pressure;
  met_on: string | null;
}

export interface Escalation {
  id: string;
  trigger: 1 | 2 | 3 | 4;
  trigger_label: string;
  subject: string;
  question: string;
  why_it_matters: string;
  options: string[];
  blocking: boolean;
  detail: string | null;
}

export interface Anomaly {
  kind: string;
  severity: "note" | "warn" | "alert";
  doc_id: string;
  page: number | null;
  char_span: [number, number] | null;
  excerpt: string;
  explanation: string;
}

export interface EvidenceItem {
  id: string;
  label: string;
  source: string;
  human_only: boolean;
  blocking: boolean;
}

export interface Readiness {
  packet_ready: boolean;
  summary: string;
  present: EvidenceItem[];
  missing_blocking: EvidenceItem[];
  missing_optional: EvidenceItem[];
  fact_gaps: { field: string; status: string | null; reason: string }[];
  unverified_critical: string[];
}

export interface Citation {
  field: string;
  value_text: string;
  status: FactStatus;
  critical: boolean;
  provenance: Provenance | null;
}

export interface Plan {
  pack: string;
  included: {
    step_id: string;
    text: string;
    evidence: string[];
    rests_on_unverified: boolean;
    citations: Citation[];
  }[];
  omitted: {
    step_id: string;
    reason: string;
    missing_facts: string[];
    missing_evidence: string[];
    is_gap: boolean;
  }[];
}

export interface DocumentMeta {
  doc_id: string;
  kind: string;
  filename: string;
  pages: number;
  ingest_method: string;
  ocr_confidence: number | null;
  trust_zone: string;
  ingested_at: string;
}

export interface Case {
  case_id: string;
  state: string;
  created_at: string;
  updated_at: string;
  pack: { id: string; name: string; version: string } | null;
  classification: {
    explanation: string;
    ambiguous: boolean;
    blocked_by: string[];
    candidates: string[];
  };
  documents: DocumentMeta[];
  ledger: Fact[];
  readiness: Readiness | null;
  deadlines: {
    regime: string | null;
    regime_blocked_by: string[];
    deadlines: Deadline[];
    blocked: { field: string; missing_fields: string[]; explanation: string }[];
    highest_pressure: Pressure;
  };
  escalations: Escalation[];
  silent: string[];
  anomalies: Anomaly[];
  plan: Plan | null;
  history: { from: string | null; to: string; at: string; by: string; reason: string }[];
  answers: { id: string; answer: string; by: string; at: string }[];
}

export interface CaseSummary {
  case_id: string;
  state: string;
  pack: string | null;
  issuer: string | null;
  service: string | null;
  escalation_count: number;
  blocking_count: number;
  top: Escalation | null;
  next_deadline: Deadline | null;
  highest_pressure: Pressure;
  updated_at: string;
}

export interface Queue {
  today: string;
  attention: CaseSummary[];
  attention_total: number;
  quiet_count: number;
}

export interface DocumentText {
  doc_id: string;
  pages: string[];
  anomalies: Anomaly[];
}

export interface AuditEvent {
  at: string;
  case_id: string;
  actor: string;
  field: string;
  outcome: "accepted" | "refused";
  error_type: string | null;
  detail: string | null;
  value: unknown;
}

export interface Health {
  ok: boolean;
  extractor: boolean;
  packs: string[];
  today: string;
  fixed_clock: boolean;
}

const USER = "advocate";

async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  const headers = new Headers(init.headers);
  headers.set("X-Overturn-User", USER);
  if (init.body && !(init.body instanceof FormData)) {
    headers.set("Content-Type", "application/json");
  }
  const response = await fetch(path, { ...init, headers });
  if (!response.ok) {
    let message = `${response.status} ${response.statusText}`;
    try {
      const body = await response.json();
      if (body?.detail) {
        message = typeof body.detail === "string" ? body.detail : JSON.stringify(body.detail);
      }
    } catch {
      // not JSON; keep the status line
    }
    throw new Error(message);
  }
  return response.json() as Promise<T>;
}

const post = (body?: unknown): RequestInit => ({
  method: "POST",
  body: body === undefined ? undefined : JSON.stringify(body),
});

export const api = {
  health: () => request<Health>("/api/health"),
  queue: () => request<Queue>("/api/queue"),
  cases: () => request<CaseSummary[]>("/api/cases"),
  getCase: (id: string) => request<Case>(`/api/cases/${id}`),
  createCase: () => request<Case>("/api/cases", post()),
  upload: (id: string, file: File, kind = "denial_letter") => {
    const form = new FormData();
    form.append("file", file);
    form.append("kind", kind);
    return request<{ doc_id: string; case: Case }>(`/api/cases/${id}/documents`, {
      method: "POST",
      body: form,
    });
  },
  document: (id: string, docId: string) =>
    request<DocumentText>(`/api/cases/${id}/documents/${docId}`),
  process: (id: string) =>
    request<{ documents_read: number; extractor: boolean; case: Case }>(
      `/api/cases/${id}/process`,
      post(),
    ),
  answer: (id: string, escalationId: string, answer: string) =>
    request<Case>(`/api/cases/${id}/escalations/${escalationId}/answer`, post({ answer })),
  confirm: (id: string, field: string) =>
    request<Case>(`/api/cases/${id}/facts/${field}/confirm`, post()),
  stateFact: (id: string, field: string, value: unknown) =>
    request<Case>(`/api/cases/${id}/facts/${field}`, {
      method: "PUT",
      body: JSON.stringify({ value }),
    }),
  attachEvidence: (id: string, evidenceId: string) =>
    request<Case>(`/api/cases/${id}/evidence/${evidenceId}`, post()),
  decision: (id: string, outcome: "overturned" | "upheld", decidedOn: string) =>
    request<Case>(`/api/cases/${id}/decision`, post({ outcome, decided_on: decidedOn })),
  markFiled: (id: string, filedOn: string) =>
    request<Case>(`/api/cases/${id}/filed`, post({ filed_on: filedOn })),
  letter: (id: string) => request<{ text: string; gaps: number }>(`/api/cases/${id}/letter`),
  audit: (id: string) => request<AuditEvent[]>(`/api/cases/${id}/audit`),
};
