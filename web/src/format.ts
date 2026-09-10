import type { Fact, Pressure } from "./api";

const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];

export function fmtDate(iso: string | null | undefined): string {
  if (!iso) return "—";
  const [y, m, d] = iso.slice(0, 10).split("-").map(Number);
  return `${MONTHS[m - 1]} ${d}, ${y}`;
}

export function fmtTime(iso: string): string {
  const d = new Date(iso);
  return `${fmtDate(iso)} ${String(d.getHours()).padStart(2, "0")}:${String(d.getMinutes()).padStart(2, "0")}`;
}

export function daysText(n: number): string {
  if (n < -1) return `${-n} days ago`;
  if (n === -1) return "yesterday";
  if (n === 0) return "today";
  if (n === 1) return "tomorrow";
  return `in ${n} days`;
}

const FIELD_LABELS: Record<string, string> = {
  "denial.notice_date": "Notice date",
  "denial.received_date": "Received on",
  "denial.reason_text": "Denial reason",
  "denial.reason_code": "Reason code",
  "denial.cited_policy_section": "Policy section cited",
  "denial.stated_appeal_deadline": "Deadline stated in letter",
  "denial.is_final": "Final determination",
  "denial.level": "Denial level",
  "service.description": "Service",
  "service.cpt_codes": "Procedure codes",
  "service.date_of_service": "Date of service",
  "service.is_pre_service": "Decided before service",
  "service.was_prior_auth_obtained": "Prior authorization obtained",
  "service.was_urgent": "Service was urgent",
  "service.provider_in_network": "Provider in network",
  "plan.issuer": "Insurer",
  "plan.covers_service": "Plan covers service",
  "patient.member_id": "Member ID",
  "patient.name": "Member",
  "provider.name": "Provider",
  "provider.is_treating_physician": "Treating physician wrote it",
  "appeal.filed_date": "Appeal filed on",
  "deadline.internal_appeal_due": "Internal appeal due",
  "deadline.external_review_due": "External review due",
  "deadline.plan_response_due": "Plan must respond by",
};

export function fieldLabel(field: string): string {
  if (FIELD_LABELS[field]) return FIELD_LABELS[field];
  const tail = field.split(".").slice(1).join(" ").replace(/_/g, " ");
  return tail.charAt(0).toUpperCase() + tail.slice(1);
}

export function valueText(fact: Pick<Fact, "kind" | "value">): string {
  const v = fact.value;
  if (v === null || v === undefined) return "";
  if (fact.kind === "date") return fmtDate(String(v));
  if (fact.kind === "bool") return v ? "Yes" : "No";
  if (Array.isArray(v)) return v.join(", ");
  return String(v);
}

export const TRIGGER_LABEL: Record<number, string> = {
  1: "Only you can obtain this",
  2: "Needs your judgment",
  3: "Deadline",
  4: "Document anomaly",
};

export const STATE_LABEL: Record<string, string> = {
  INTAKE: "Intake",
  CLASSIFIED: "Classified",
  EVIDENCE_GAP: "Evidence gap",
  AWAITING_DOCUMENT: "Awaiting a document",
  PACKET_READY: "Packet ready",
  SUBMITTED: "Filed",
  AWAITING_RESPONSE: "Awaiting plan response",
  DECISION: "Decision received",
  RESOLVED_OVERTURNED: "Overturned",
  RESOLVED_UPHELD: "Upheld",
  EXTERNAL_REVIEW_ELIGIBLE: "Eligible for external review",
  EXTERNAL_REVIEW: "External review",
  CLOSED_DEADLINE_MISSED: "Closed — deadline missed",
};

export const PRESSURE_LABEL: Record<Pressure, string> = {
  none: "",
  info: "within 30 days",
  elevated: "within 14 days",
  urgent: "within 7 days",
  critical: "within 3 days",
  expired: "window closed",
};

export function groupOf(field: string): string {
  const head = field.split(".")[0];
  if (head === "denial") return "The denial";
  if (head === "service" || head === "provider") return "The service";
  if (head === "plan" || head === "patient") return "Plan and member";
  if (head === "appeal") return "The appeal";
  return "Other";
}
