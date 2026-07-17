import { Link } from 'react-router-dom'
import {
  AlertTriangle,
  ArrowRight,
  Check,
  ChevronRight,
  CircleDot,
  Clock3,
  FileSearch,
  Fingerprint,
  Gauge,
  Globe2,
  Plus,
  ShieldAlert,
  ShieldCheck,
  Sparkles,
} from 'lucide-react'
import {
  auditPhases,
  coverageSeries,
  dashboardMetrics,
  findings,
  providers,
  syntheticRun,
} from '@ariadne/synthetic-data'
import {
  Badge,
  Button,
  Metric,
  PageHeader,
  Panel,
  TextLink,
} from '../components/Primitives'
import { Sparkline } from '../components/Sparkline'

const toneMap = {
  cyan: 'cyan',
  violet: 'violet',
  green: 'green',
  amber: 'amber',
} as const

export function DashboardPage() {
  return (
    <div className="page dashboard-page" data-testid="route-ready">
      <PageHeader
        eyebrow="System overview · 11 Jul 2026"
        title="Mission Control"
        description="Review what needs human judgment, monitor the simulated baseline, and keep coverage gaps visible."
        meta={
          <>
            <Badge tone="green" dot>Vault healthy</Badge>
            <Badge tone="cyan">Local-first policy</Badge>
            <Badge tone="violet">6 decisions pending</Badge>
          </>
        }
        actions={
          <>
            <Button variant="secondary"><Sparkles size={14} /> Review queue</Button>
            <Link className="button button--primary" to="/audits/new">
              <Plus size={14} /> New audit
            </Link>
          </>
        }
      />

      <div className="dashboard-hero">
        <div className="dashboard-hero__copy">
          <p className="eyebrow">Operational readiness</p>
          <h2>Stay calm, move faster, and keep every decision traceable.</h2>
          <p>Every review step feels clearer now, with better cues for evidence, priority, and the next best action.</p>
        </div>
        <div className="dashboard-hero__actions">
          <Badge tone="cyan" dot>Encrypted workspace</Badge>
          <Badge tone="green">Evidence-first flow</Badge>
          <Badge tone="violet">Human review ready</Badge>
        </div>
      </div>

      <div className="metric-grid">
        {dashboardMetrics.map((metric) => (
          <Metric
            key={metric.label}
            label={metric.label}
            value={metric.value}
            detail={metric.delta}
            tone={toneMap[metric.tone]}
          />
        ))}
      </div>

      <div className="page-grid dashboard-grid">
        <Panel
          className="span-8 panel--signal dashboard-run"
          eyebrow="Active audit · simulated"
          title={syntheticRun.title}
          action={<Badge tone="cyan" dot>{syntheticRun.phase}</Badge>}
        >
          <div className="dashboard-run__body">
            <div className="coverage-dial" style={{ '--progress': `${syntheticRun.progress * 3.6}deg` } as React.CSSProperties}>
              <div className="coverage-dial__center">
                <strong>{syntheticRun.progress}%</strong>
                <span>run progress</span>
              </div>
            </div>
            <div className="audit-phase-list">
              {auditPhases.map((phase) => (
                <div className={`audit-phase is-${phase.status}`} key={phase.label}>
                  <span className="audit-phase__icon">
                    {phase.status === 'complete' ? <Check size={12} /> : <CircleDot size={12} />}
                  </span>
                  <div>
                    <strong>{phase.label}</strong>
                    <small>{phase.detail}</small>
                  </div>
                </div>
              ))}
            </div>
            <div className="dashboard-run__summary">
              <div><Clock3 size={14} /><span>ETA</span><strong>{syntheticRun.eta}</strong></div>
              <div><Gauge size={14} /><span>Workers</span><strong>4 / 6</strong></div>
              <div><Fingerprint size={14} /><span>Graph edges</span><strong>43</strong></div>
              <Link to={`/operations/${syntheticRun.id}`}>
                Open console <ArrowRight size={13} />
              </Link>
            </div>
          </div>
        </Panel>

        <Panel
          className="span-4 dashboard-coverage"
          eyebrow="Measured coverage"
          title="Checks observed"
          action={<span className="mono dashboard-coverage__value">142 / 186</span>}
        >
          <div className="panel__body">
            <Sparkline values={coverageSeries} label="Synthetic completed-check trend" />
            <div className="coverage-legend">
              <div><span className="legend-dot legend-dot--green" />Complete <strong>142</strong></div>
              <div><span className="legend-dot legend-dot--amber" />Blocked <strong>2</strong></div>
              <div><span className="legend-dot legend-dot--blue" />Queued <strong>39</strong></div>
              <div><span className="legend-dot legend-dot--rose" />Failed <strong>3</strong></div>
            </div>
            <div className="coverage-footnote">
              <ShieldAlert size={13} />
              <span>No result is interpreted as nonexistence.</span>
            </div>
          </div>
        </Panel>

        <Panel
          className="span-7 dashboard-attention"
          eyebrow="Human review"
          title="Attention queue"
          action={<TextLink>View all findings</TextLink>}
        >
          {findings.slice(0, 3).map((finding) => (
            <Link className="attention-row" to={`/findings/${finding.id}`} key={finding.id}>
              <span className={`status-icon status-icon--${finding.severity === 'high' ? 'amber' : finding.severity === 'medium' ? 'violet' : 'cyan'}`}>
                {finding.outcome === 'AMBIGUOUS' ? <AlertTriangle size={14} /> : <FileSearch size={14} />}
              </span>
              <div className="attention-row__copy">
                <strong>{finding.title}</strong>
                <span>{finding.summary}</span>
              </div>
              <div className="attention-row__meta">
                <Badge tone={finding.confidence > 90 ? 'green' : finding.confidence > 70 ? 'violet' : 'amber'}>
                  {finding.confidence}% confidence
                </Badge>
                <small>{finding.ownership}</small>
              </div>
              <ChevronRight size={14} />
            </Link>
          ))}
        </Panel>

        <Panel
          className="span-5 dashboard-providers"
          eyebrow="Source Radar"
          title="Provider posture"
          action={<Link className="text-link" to="/providers">Registry <ArrowRight size={12} /></Link>}
        >
          <div className="provider-mini-grid">
            {providers.slice(0, 4).map((provider) => (
              <div className="provider-mini" key={provider.id}>
                <span className={`provider-mini__health is-${provider.health}`} />
                <div><strong>{provider.name}</strong><small>{provider.country} · {provider.type.replaceAll('_', ' ')}</small></div>
                <span className="mono">{provider.coverage}%</span>
              </div>
            ))}
          </div>
          <div className="provider-policy-strip">
            <Globe2 size={14} />
            <div><strong>EU allowlist active</strong><span>1 worldwide provider held for approval</span></div>
            <ShieldCheck size={15} />
          </div>
        </Panel>
      </div>
    </div>
  )
}
