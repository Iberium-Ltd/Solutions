import { useMemo, useState } from 'react'
import {
  AlertTriangle,
  CheckCircle2,
  CirclePause,
  Clock3,
  Download,
  FileText,
  Pause,
  Play,
  RotateCcw,
  ShieldAlert,
  Square,
  Terminal,
  Users,
  Workflow,
} from 'lucide-react'
import {
  operationLogs,
  operationTasks,
  syntheticRun,
} from '@ariadne/synthetic-data'
import { usePrototypeStore } from '../app/prototypeStore'
import {
  Badge,
  Button,
  PageHeader,
  Panel,
  Progress,
} from '../components/Primitives'
import '../styles/pages-results.css'

const stateTone = {
  complete: 'green',
  running: 'cyan',
  blocked: 'amber',
  queued: 'blue',
} as const

const logTone = {
  INFO: 'blue',
  PASS: 'green',
  WARN: 'amber',
  FOUND: 'violet',
} as const

export function OperationsPage() {
  const { simulationPaused, toggleSimulation } = usePrototypeStore()
  const [selectedTask, setSelectedTask] = useState<string>(operationTasks[2].id)
  const [logFilter, setLogFilter] = useState<'all' | 'warnings'>('all')
  const [cancelled, setCancelled] = useState(false)

  const visibleLogs = useMemo(
    () =>
      logFilter === 'warnings'
        ? operationLogs.filter((entry) => entry[1] === 'WARN')
        : operationLogs,
    [logFilter],
  )

  const runState = cancelled
    ? 'Cancelled safely'
    : simulationPaused
      ? 'Paused by operator'
      : syntheticRun.phase

  return (
    <div className="page operations-page" data-testid="route-ready">
      <PageHeader
        eyebrow="Live operations · synthetic run"
        title={syntheticRun.title}
        description="A deterministic Phase 1 playback of the approved search plan. No provider calls or external requests are made."
        meta={
          <>
            <Badge tone={cancelled ? 'rose' : simulationPaused ? 'amber' : 'cyan'} dot>
              {runState}
            </Badge>
            <Badge>{syntheticRun.shortId}</Badge>
            <span className="operations-page__started mono">
              Started {syntheticRun.startedAt}
            </span>
          </>
        }
        actions={
          <>
            <Button
              variant="secondary"
              onClick={toggleSimulation}
              disabled={cancelled}
            >
              {simulationPaused ? <Play size={14} /> : <Pause size={14} />}
              {simulationPaused ? 'Resume' : 'Pause'}
            </Button>
            <Button
              variant="danger"
              onClick={() => setCancelled(true)}
              disabled={cancelled}
            >
              <Square size={13} /> Cancel run
            </Button>
          </>
        }
      />

      <div className="compact-workflow-action compact-workflow-action--blocked" role="region" aria-label="Blocked task recovery">
        <div>
          <strong>1 blocked task</strong>
          <span>No image transmitted · retention unknown</span>
        </div>
        <Button variant="secondary" size="compact"><FileText size={12} /> Review boundary</Button>
        <Button variant="ghost" size="compact"><Terminal size={12} /> Skip provider</Button>
      </div>

      <Panel className="operations-status panel--signal">
        <div className="operations-status__lead">
          <div className="operations-status__label">
            <span className="operations-status__pulse" aria-hidden="true" />
            <div>
              <span>Simulated run — no external requests</span>
              <strong>{runState}</strong>
            </div>
          </div>
          <div className="operations-status__progress">
            <div className="space-between">
              <span>
                142 of 186 bounded checks complete
              </span>
              <strong className="mono">{cancelled ? '68' : syntheticRun.progress}%</strong>
            </div>
            <Progress value={syntheticRun.progress} label="142 of 186 checks complete, 68 percent" />
          </div>
        </div>
        <div className="operations-status__facts" aria-label="Run summary">
          <div><span>ETA</span><strong className="mono">{cancelled ? '—' : syntheticRun.eta}</strong></div>
          <div><span>API cost</span><strong className="mono">€0.00</strong></div>
          <div><span>Queries</span><strong className="mono">186</strong></div>
          <div><span>Findings</span><strong className="mono">27</strong></div>
          <div><span>Graph change</span><strong className="mono">+9 / +12</strong></div>
          <div><span>Evidence</span><strong className="mono">14 sealed</strong></div>
        </div>
      </Panel>

      <section className="operations-counters" aria-label="Worker and queue summary">
        <article>
          <Users size={15} />
          <div><span>Active workers</span><strong className="mono">2 / 4</strong></div>
        </article>
        <article>
          <Workflow size={15} />
          <div><span>Queued tasks</span><strong className="mono">1</strong></div>
        </article>
        <article>
          <CheckCircle2 size={15} />
          <div><span>Completed</span><strong className="mono">2</strong></div>
        </article>
        <article className="is-warning">
          <ShieldAlert size={15} />
          <div><span>Needs action</span><strong className="mono">1 blocked</strong></div>
        </article>
      </section>

      <Panel
        className="operations-tasks"
        eyebrow="Execution plan"
        title="Provider tasks"
        action={
          <div className="inline">
            <Badge tone="green">3 providers healthy</Badge>
            <Button variant="ghost" size="compact">
              <RotateCcw size={12} /> Retry selected
            </Button>
          </div>
        }
      >
        <div className="operations-table-wrap">
          <table className="data-table operations-table">
            <thead>
              <tr>
                <th scope="col">Task</th>
                <th scope="col">Provider</th>
                <th scope="col">State</th>
                <th scope="col">Duration</th>
                <th scope="col">Results</th>
                <th scope="col"><span className="sr-only">Action</span></th>
              </tr>
            </thead>
            <tbody>
              {operationTasks.map((task) => (
                <tr
                  key={task.id}
                  className={selectedTask === task.id ? 'is-selected' : undefined}
                >
                  <td>
                    <button
                      className="operations-task-link"
                      type="button"
                      onClick={() => setSelectedTask(task.id)}
                      aria-pressed={selectedTask === task.id}
                    >
                      <span>{task.name}</span>
                      <small className="mono">{task.id}</small>
                    </button>
                  </td>
                  <td>{task.provider}</td>
                  <td><Badge tone={stateTone[task.state]} dot>{task.state}</Badge></td>
                  <td className="mono">{task.duration}</td>
                  <td className="mono">{task.results}</td>
                  <td>
                    <Button
                      variant="ghost"
                      size="compact"
                      onClick={() => setSelectedTask(task.id)}
                    >
                      Details
                    </Button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Panel>

      <div className="operations-bottom">
        <Panel
          className="operations-log"
          eyebrow="Local event stream"
          title="Structured execution log"
          action={
            <div className="inline">
              <div className="segmented-control" aria-label="Log filter">
                <button
                  type="button"
                  className={logFilter === 'all' ? 'is-active' : undefined}
                  onClick={() => setLogFilter('all')}
                >
                  All
                </button>
                <button
                  type="button"
                  className={logFilter === 'warnings' ? 'is-active' : undefined}
                  onClick={() => setLogFilter('warnings')}
                >
                  Warnings
                </button>
              </div>
              <Button variant="ghost" size="compact">
                <Download size={12} /> Export
              </Button>
            </div>
          }
        >
          <div className="operations-log__rows" role="log" aria-label="Synthetic execution log">
            {visibleLogs.map(([time, level, source, message]) => (
              <div className="operations-log__row" key={`${time}-${source}`}>
                <time className="mono">{time}</time>
                <Badge tone={logTone[level]}>{level}</Badge>
                <strong>{source}</strong>
                <span>{message}</span>
              </div>
            ))}
          </div>
        </Panel>

        <Panel
          className="operations-action"
          eyebrow="1 unresolved request"
          title="Human action required"
          action={<Badge tone="violet">Manual</Badge>}
        >
          <div className="operations-action__body">
            <span className="status-icon status-icon--violet"><CirclePause size={15} /></span>
            <div>
              <strong>Image comparison remains blocked</strong>
              <p>No image was transmitted. Review the provider boundary before approving any external disclosure.</p>
            </div>
          </div>
          <div className="operations-action__meta">
            <span><Clock3 size={12} /> Waiting 04m 16s</span>
            <span><AlertTriangle size={12} /> Retention unknown</span>
          </div>
          <div className="operations-action__buttons">
            <Button variant="secondary" size="compact"><FileText size={12} /> Review boundary</Button>
            <Button variant="ghost" size="compact"><Terminal size={12} /> Skip provider</Button>
          </div>
        </Panel>
      </div>
    </div>
  )
}
