export type Status = 'MATCHED' | 'AUTO_RESOLVED' | 'NEEDS_REVIEW' | 'UNRESOLVED'

export interface Summary {
  total_cases: number
  matched: number
  auto_resolved: number
  needs_review: number
  unresolved: number
  match_rate: number
  auto_resolution_rate: number
  processing_time_ms: number
}

export interface CaseSummary {
  case_id: string
  invoice_id: string
  gateway_transaction_id: string | null
  bank_settlement_id: string | null
  status: Status
  discrepancy_type: string
  reason: string
  confidence: string
  requires_human_review: boolean
  evidence_ids: string[]
}

export interface InvoiceRecord {
  invoice_id: string
  amount_inr: string
  invoice_date: string
  currency: string
}

export interface GatewayRecord {
  transaction_id: string
  invoice_reference_id: string
  gross_amount_inr: string
  fee_inr: string
  net_amount_inr: string
  transaction_date: string
  currency: string
}

export interface BankRecord {
  settlement_id: string
  reference_id: string
  amount_inr: string
  settlement_date: string
  currency: string
}

export interface ReconciliationResult {
  case_id: string
  status: Status
  invoice_amount_inr: string
  gateway_amount_inr: string | null
  gateway_fee_inr: string
  expected_settlement_inr: string | null
  actual_settlement_inr: string | null
  variance_inr: string | null
  discrepancy_type: string
  reason: string
  rule_applied: string
  confidence: string
  requires_human_review: boolean
  evidence_ids: string[]
}

export interface CaseDetail {
  case_id: string
  invoice: InvoiceRecord
  gateway: GatewayRecord[]
  bank: BankRecord[]
  reconciliation: ReconciliationResult
  evidence: Record<string, string>
  deterministic_explanation: string
  requires_human_review: boolean
}

export interface InvestigationResult {
  case_id: string
  investigation: {
    case_id: string
    conclusion: string
    discrepancy_type: string
    confidence: number
    evidence_ids: string[]
    evidence_summary: string
    recommended_action: string
    requires_human_review: boolean
    ai_generated: boolean
    guardrail_flags: string[]
  }
}

export interface ControllerCaseReport {
  case_id: string
  deterministic_status: Status
  deterministic_reason: string
  deterministic_rule: string
  evidence_ids: string[]
  requires_human_review: boolean
  investigation: InvestigationResult['investigation'] | null
}

export interface ControllerRunResult {
  total_records_processed: number
  matched_count: number
  auto_resolved_count: number
  needs_review_count: number
  unresolved_count: number
  match_rate: number
  auto_resolution_rate: number
  total_resolved_count: number
  resolved_rate: number
  processing_time_ms: number
  total_exception_count: number
  ai_investigations_attempted: number
  ai_investigations_successfully_completed: number
  ai_fallbacks: number
  ai_investigations_skipped: number
  unresolved_exceptions: ControllerCaseReport[]
  human_review_cases: ControllerCaseReport[]
  skipped_ai_cases: ControllerCaseReport[]
  audit_cases: ControllerCaseReport[]
}

const API_BASE_URL = import.meta.env.VITE_API_BASE_URL ?? ''

async function request<T>(path: string, options?: RequestInit): Promise<T> {
  const response = await fetch(`${API_BASE_URL}${path}`, options)
  if (!response.ok) {
    const body = await response.json().catch(() => ({})) as { detail?: string }
    throw new Error(body.detail ?? `Request failed with status ${response.status}`)
  }
  return response.json() as Promise<T>
}

export const getSummary = () => request<Summary>('/api/summary')
export const getCases = (status?: Status, limit = 50, offset = 0) => {
  const params = new URLSearchParams({ limit: String(limit), offset: String(offset) })
  if (status) params.set('status', status)
  return request<CaseSummary[]>(`/api/cases?${params.toString()}`)
}
export const getCase = (caseId: string) => request<CaseDetail>(`/api/cases/${caseId}`)
export const investigateCase = (caseId: string) => request<InvestigationResult>(`/api/cases/${caseId}/investigate`, { method: 'POST' })
export const runFinanceController = () => request<ControllerRunResult>('/api/agent/run', { method: 'POST' })