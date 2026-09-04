import { useEffect, useState, type ReactNode } from 'react'
import {
  getCase,
  getCases,
  getSummary,
  investigateCase,
  type CaseDetail,
  type CaseSummary,
  type InvestigationResult,
  type Status,
  type Summary,
} from './api/client'

type Page = 'reconciliation' | 'exceptions' | 'audit'
type ExceptionFilter = 'ALL' | 'NEEDS_REVIEW' | 'UNRESOLVED'

const statusLabels: Record<Status, string> = {
  MATCHED: 'Matched', AUTO_RESOLVED: 'Auto-resolved', NEEDS_REVIEW: 'Needs review', UNRESOLVED: 'Unresolved',
}

function App() {
  const [page, setPage] = useState<Page>('reconciliation')
  const [summary, setSummary] = useState<Summary | null>(null)
  const [cases, setCases] = useState<CaseSummary[]>([])
  const [selectedCase, setSelectedCase] = useState<CaseDetail | null>(null)
  const [investigation, setInvestigation] = useState<InvestigationResult | null>(null)
  const [exceptionFilter, setExceptionFilter] = useState<ExceptionFilter>('ALL')
  const [search, setSearch] = useState('')
  const [loading, setLoading] = useState(false)
  const [detailLoading, setDetailLoading] = useState(false)
  const [investigating, setInvestigating] = useState(false)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    setLoading(true)
    const casesRequest = page === 'exceptions' && exceptionFilter === 'ALL'
      ? Promise.all([getCases('NEEDS_REVIEW'), getCases('UNRESOLVED')]).then(([needsReview, unresolved]) => [...needsReview, ...unresolved])
      : page === 'exceptions' ? getCases(exceptionFilter === 'NEEDS_REVIEW' || exceptionFilter === 'UNRESOLVED' ? exceptionFilter : undefined) : getCases(undefined)
    Promise.all([getSummary(), casesRequest])
      .then(([nextSummary, nextCases]) => { setSummary(nextSummary); setCases(nextCases); setError(null) })
      .catch(() => setError('Unable to load LedgerOS data. Please check the API connection.'))
      .finally(() => setLoading(false))
  }, [exceptionFilter, page])

  const visibleCases = cases.filter((item) => {
    const query = search.toLowerCase()
    return item.case_id.toLowerCase().includes(query) || item.invoice_id.toLowerCase().includes(query) || item.reason.toLowerCase().includes(query)
  })

  const openCase = (caseId: string) => {
    setDetailLoading(true); setError(null); setInvestigation(null)
    getCase(caseId).then(setSelectedCase).catch(() => setError('This case could not be found. Please try again.')).finally(() => setDetailLoading(false))
  }

  const runInvestigation = () => {
    if (!selectedCase) return
    setInvestigating(true); setInvestigation(null); setError(null)
    investigateCase(selectedCase.case_id).then(setInvestigation).catch(() => setError('Investigation failed. The supplied evidence was not changed.')).finally(() => setInvestigating(false))
  }

  const navigate = (nextPage: Page) => { setPage(nextPage); setError(null); if (nextPage === 'exceptions') setExceptionFilter('ALL') }

  return <div className="app-shell">
    <Sidebar page={page} onNavigate={navigate} />
    <main className="main-content">
      <Header page={page} />
      {page === 'reconciliation' && <Reconciliation summary={summary} cases={visibleCases} loading={loading} error={error} onOpenCase={openCase} />}
      {page === 'exceptions' && <Exceptions cases={visibleCases} summary={summary} filter={exceptionFilter} search={search} loading={loading} error={error} onFilter={setExceptionFilter} onSearch={setSearch} onOpenCase={openCase} />}
      {page === 'audit' && <AuditTrail selectedCase={selectedCase} investigation={investigation} />}
    </main>
    {detailLoading && <div className="drawer-backdrop"><aside className="drawer"><div className="section-kicker">CASE DETAIL</div><h2>Loading case...</h2></aside></div>}
    {selectedCase && !detailLoading && <CaseDrawer caseDetail={selectedCase} investigation={investigation} investigating={investigating} error={error} onInvestigate={runInvestigation} onClose={() => setSelectedCase(null)} />}
  </div>
}

function Sidebar({ page, onNavigate }: { page: Page; onNavigate: (page: Page) => void }) {
  return <aside className="sidebar"><div className="brand"><div className="brand-mark">L</div><div><strong>LedgerOS</strong><span>Finance control system</span></div></div><nav className="nav-list"><NavItem icon="◈" label="Reconciliation" active={page === 'reconciliation'} onClick={() => onNavigate('reconciliation')} /><NavItem icon="!" label="Exceptions" active={page === 'exceptions'} onClick={() => onNavigate('exceptions')} /><NavItem icon="◷" label="Audit trail" active={page === 'audit'} onClick={() => onNavigate('audit')} /></nav><div className="sidebar-footer"><div className="layer"><i className="layer-dot deterministic" />Deterministic rules<span className="layer-note">Financial truth and matching</span></div><div className="layer"><i className="layer-dot ai" />AI investigation<span className="layer-note">Evidence-based explanations</span></div><div className="version">LEDGEROS / 0.1</div></div></aside>
}

function NavItem({ icon, label, active, onClick }: { icon: string; label: string; active: boolean; onClick: () => void }) {
  return <button className={`nav-item ${active ? 'active' : ''}`} onClick={onClick}><span className="nav-icon">{icon}</span>{label}</button>
}

function Header({ page }: { page: Page }) {
  const title = page === 'reconciliation' ? 'Control center' : page === 'exceptions' ? 'Exceptions' : 'Audit trail'
  const subtitle = page === 'exceptions' ? 'Cases requiring investigation or human review.' : page === 'audit' ? 'Read-only case investigation and audit view.' : 'Monitor every financial record from ingest to resolution.'
  return <header className="topbar"><div><div className="breadcrumb">OPERATIONS <span>/</span> {title.toUpperCase()}</div><h1>{title}</h1><p>{subtitle}</p></div><div className="system-status"><span className="live-dot" />System operational<span className="status-divider" />Today</div></header>
}

function Reconciliation({ summary, cases, loading, error, onOpenCase }: { summary: Summary | null; cases: CaseSummary[]; loading: boolean; error: string | null; onOpenCase: (id: string) => void }) {
  return <><section className="hero-row"><div><div className="eyebrow">RECONCILIATION RUN</div><h2>Financial truth, <em>verified.</em></h2><p>Deterministic matching with evidence-led exception handling.</p></div><div className="hero-meta"><span className="meta-label">LAST PROCESSED</span><strong>{summary?.total_cases ?? '—'}</strong><span>records in current run</span></div></section><section className="kpi-grid"><Kpi label="Total cases" value={summary?.total_cases} /><Kpi label="Matched" value={summary?.matched} tone="green" detail={summary ? `${(summary.match_rate * 100).toFixed(1)}% match rate` : undefined} /><Kpi label="Auto-resolved" value={summary?.auto_resolved} tone="cyan" detail={summary ? `${(summary.auto_resolution_rate * 100).toFixed(1)}% of cases` : undefined} /><Kpi label="Needs review" value={summary?.needs_review} tone="amber" /><Kpi label="Unresolved" value={summary?.unresolved} tone="red" /></section><CaseQueue cases={cases} loading={loading} error={error} onOpenCase={onOpenCase} /></>
}

function Exceptions({ cases, summary, filter, search, loading, error, onFilter, onSearch, onOpenCase }: { cases: CaseSummary[]; summary: Summary | null; filter: ExceptionFilter; search: string; loading: boolean; error: string | null; onFilter: (filter: ExceptionFilter) => void; onSearch: (value: string) => void; onOpenCase: (id: string) => void }) {
  return <section className="queue-section"><div className="queue-heading"><div><div className="section-kicker">EXCEPTION QUEUE</div><h2>Cases requiring investigation or human review.</h2></div><div className="queue-count">{cases.length} <span>visible</span></div></div><div className="kpi-grid"><Kpi label="Needs review" value={summary?.needs_review} tone="amber" /><Kpi label="Unresolved" value={summary?.unresolved} tone="red" /></div><div className="queue-controls"><div className="filter-tabs"><Filter label="All Exceptions" active={filter === 'ALL'} onClick={() => onFilter('ALL')} /><Filter label="Needs Review" active={filter === 'NEEDS_REVIEW'} onClick={() => onFilter('NEEDS_REVIEW')} /><Filter label="Unresolved" active={filter === 'UNRESOLVED'} onClick={() => onFilter('UNRESOLVED')} /></div><label className="search">⌕<input value={search} onChange={(event) => onSearch(event.target.value)} placeholder="Search by case ID" /></label></div><CaseTable cases={cases} loading={loading} error={error} onOpenCase={onOpenCase} /></section>
}

function CaseQueue({ cases, loading, error, onOpenCase }: { cases: CaseSummary[]; loading: boolean; error: string | null; onOpenCase: (id: string) => void }) {
  return <section className="queue-section"><div className="queue-heading"><div><div className="section-kicker">EXCEPTION QUEUE</div><h2>Cases requiring attention</h2><p>Open a case to inspect its evidence and deterministic decision.</p></div><div className="queue-count">{cases.length} <span>visible</span></div></div><CaseTable cases={cases} loading={loading} error={error} onOpenCase={onOpenCase} /></section>
}

function CaseTable({ cases, loading, error, onOpenCase }: { cases: CaseSummary[]; loading: boolean; error: string | null; onOpenCase: (id: string) => void }) {
  return <>{error && <div className="human-review"><span>REQUEST FAILED</span><b>{error}</b></div>}<div className="table-wrap"><table><thead><tr><th>Case</th><th>Status</th><th>Discrepancy</th><th>Reason</th><th>Confidence</th></tr></thead><tbody>{loading && <tr><td colSpan={5}>Loading cases...</td></tr>}{!loading && cases.map((item) => <tr key={item.case_id} onClick={() => onOpenCase(item.case_id)}><td><strong>{item.case_id}</strong><small>{item.invoice_id}</small></td><td><StatusBadge status={item.status} /></td><td>{item.discrepancy_type}</td><td className="reason-cell">{item.reason}</td><td>{item.confidence}</td></tr>)}{!loading && cases.length === 0 && <tr><td colSpan={5}>No cases found.</td></tr>}</tbody></table></div></>
}

function CaseDrawer({ caseDetail, investigation, investigating, error, onInvestigate, onClose }: { caseDetail: CaseDetail; investigation: InvestigationResult | null; investigating: boolean; error: string | null; onInvestigate: () => void; onClose: () => void }) {
  const result = caseDetail.reconciliation
  const canInvestigate = result.status === 'NEEDS_REVIEW' || result.status === 'UNRESOLVED'
  return <div className="drawer-backdrop" onClick={onClose}><aside className="drawer" onClick={(event) => event.stopPropagation()}><div className="drawer-top"><div><div className="section-kicker">CASE DETAIL</div><h2>{result.case_id}</h2></div><button className="icon-button" onClick={onClose} aria-label="Close">×</button></div><div className="drawer-status"><StatusBadge status={result.status} /><span className="rule-label">{result.rule_applied}</span></div><div className="decision-panel"><div className="section-kicker">DETERMINISTIC DECISION</div><p><strong>DISCREPANCY:</strong> {result.discrepancy_type}</p><p><strong>REASON:</strong> {caseDetail.deterministic_explanation || result.reason}</p></div><div className="source-grid"><EvidenceCard title="INVOICE"><Evidence label="Invoice ID" value={caseDetail.invoice.invoice_id} /><Evidence label="Amount" value={`${caseDetail.invoice.amount_inr} ${caseDetail.invoice.currency}`} /><Evidence label="Date" value={caseDetail.invoice.invoice_date} /></EvidenceCard><EvidenceCard title="GATEWAY">{caseDetail.gateway.length ? <><Evidence label="Transaction ID" value={caseDetail.gateway[0].transaction_id} /><Evidence label="Gross" value={caseDetail.gateway[0].gross_amount_inr} /><Evidence label="Fee" value={caseDetail.gateway[0].fee_inr} /><Evidence label="Net" value={caseDetail.gateway[0].net_amount_inr} /><Evidence label="Date" value={caseDetail.gateway[0].transaction_date} /></> : <span>Gateway transaction not found</span>}</EvidenceCard><EvidenceCard title="BANK SETTLEMENT">{caseDetail.bank.length ? <><Evidence label="Settlement ID" value={caseDetail.bank[0].settlement_id} /><Evidence label="Amount" value={caseDetail.bank[0].amount_inr} /><Evidence label="Date" value={caseDetail.bank[0].settlement_date} /></> : <div className="missing-record"><span>!</span>Bank settlement not found</div>}</EvidenceCard></div>{canInvestigate && <div className="investigation-action"><button className="row-action" onClick={onInvestigate} disabled={investigating}>{investigating ? 'Investigating supplied evidence…' : 'Investigate with AI'}</button></div>}{error && <div className="human-review"><span>REQUEST FAILED</span><b>{error}</b></div>}{investigation && <Investigation result={investigation} />}</aside></div>
}

function Investigation({ result }: { result: InvestigationResult }) {
  const item = result.investigation
  return <div className="audit-panel"><div className="section-kicker">AI INVESTIGATION</div>{!item.ai_generated && <p className="fallback-note">Deterministic fallback — AI API key not configured</p>}{item.requires_human_review && <div className="human-review"><span>HUMAN REVIEW REQUIRED</span><b>LedgerOS will not modify financial records based solely on AI reasoning.</b></div>}<div className="investigation-fields"><Evidence label="Conclusion" value={item.conclusion} /><Evidence label="Confidence" value={`${(item.confidence * 100).toFixed(1)}%`} /><Evidence label="Evidence Summary" value={item.evidence_summary} /><Evidence label="Evidence IDs" value={item.evidence_ids.join(', ') || 'None provided'} /><Evidence label="Recommended Action" value={item.recommended_action} /><Evidence label="Human Review Required" value={item.requires_human_review ? 'Yes' : 'No'} /><Evidence label="AI Generated" value={item.ai_generated ? 'Yes' : 'No'} /><Evidence label="Guardrail Flags" value={item.guardrail_flags.join(', ') || 'None'} /></div></div>
}

function AuditTrail({ selectedCase, investigation }: { selectedCase: CaseDetail | null; investigation: InvestigationResult | null }) {
  return <section className="queue-section"><div className="section-kicker">READ-ONLY AUDIT VIEW</div><h2>Case investigation and audit trail</h2><p>This view is derived from the currently selected case and investigation state. Persistent audit records are not available yet.</p>{!selectedCase ? <div className="human-review"><span>NO CASE SELECTED</span><b>Select an exception to review its audit information.</b></div> : <div className="audit-panel"><Evidence label="Case ID" value={selectedCase.case_id} /><Evidence label="Deterministic decision" value={selectedCase.reconciliation.reason} /><Evidence label="Evidence IDs" value={selectedCase.reconciliation.evidence_ids.join(', ') || 'None provided'} /><Evidence label="Investigation conclusion" value={investigation?.investigation.conclusion ?? 'No investigation run'} /><Evidence label="Confidence" value={investigation ? `${(investigation.investigation.confidence * 100).toFixed(1)}%` : selectedCase.reconciliation.confidence} /><Evidence label="Recommended action" value={investigation?.investigation.recommended_action ?? 'No investigation run'} /><Evidence label="Human review requirement" value={(investigation?.investigation.requires_human_review ?? selectedCase.requires_human_review) ? 'Required' : 'Not required'} /></div>}</section>
}

function EvidenceCard({ title, children }: { title: string; children: ReactNode }) {
  return <div className="source-card"><div className="source-head"><span>SOURCE</span><strong>{title}</strong></div><dl>{children}</dl></div>
}

function Evidence({ label, value }: { label: string; value: string }) {
  return <div><dt>{label}</dt><dd>{value}</dd></div>
}

function StatusBadge({ status }: { status: Status }) {
  return <span className={`status status-${status.toLowerCase()}`}><i className="status-dot" />{statusLabels[status]}</span>
}

function Kpi({ label, value, tone, detail }: { label: string; value?: number; tone?: string; detail?: string }) {
  return <div className={`kpi-card ${tone ?? ''}`}><div className="kpi-label">{label}</div><div className="kpi-value">{value ?? '—'}</div><div className="kpi-detail">{detail ?? 'Current reconciliation run'}</div></div>
}

function Filter({ label, active, onClick }: { label: string; active: boolean; onClick: () => void }) {
  return <button className={`filter ${active ? 'active' : ''}`} onClick={onClick}>{label}</button>
}

export default App
