import { useEffect, useRef, useState } from 'react'
import { createRoot } from 'react-dom/client'
import { Activity, Archive, Bot, CheckCircle2, ChevronDown, ChevronRight, CircleAlert, Command, Cpu, FileCode2, GitBranch, Layers, Layers3, Link2, ListChecks, Loader2, MemoryStick, OctagonX, Pause, Play, Settings, TerminalSquare, Wifi, XCircle, Zap } from 'lucide-react'
import { HttpBridge, RuntimeSnapshot, TaskStatus, ConcurrentTask, ConcurrentEvent } from './bridge'
import './styles.css'
import './navigation.css'

const bridge = new HttpBridge()
const nav = [
  ['command', 'Command', Command], ['task', 'Current Task', Bot], ['plan', 'Plan', ListChecks], ['concurrent', 'Concurrent Flow', GitBranch], ['execution', 'Execution', Layers3], ['terminal', 'Terminal', TerminalSquare], ['memory', 'Memory', MemoryStick], ['artifacts', 'Artifacts', Archive], ['activity', 'Activity', Activity], ['diagnostics', 'Diagnostics', Cpu],
] as const
const statusLabel: Record<RuntimeSnapshot['mode'], string> = { initializing: 'INITIALIZING', planning: 'PLANNING', executing: 'EXECUTING', reviewing: 'REVIEWING', finished: 'COMPLETED', error: 'ERROR' }

function App() {
  const [snapshot, setSnapshot] = useState<RuntimeSnapshot>(bridge.getSnapshot())
  const [view, setView] = useState('command')
  const [goal, setGoal] = useState('')
  const [offlineNotice, setOfflineNotice] = useState(false)
  useEffect(() => bridge.subscribe(setSnapshot), [])
  const plan = snapshot.task_plan
  const workflow = snapshot.execution_workflow
  const activeTask = plan?.tasks.find((task) => task.status === 'in_progress')
  const submit = async (event: React.FormEvent) => { event.preventDefault(); if (!goal.trim()) return; if (!snapshot.backend?.connected) { setOfflineNotice(true); return } await bridge.submitGoal(goal); setView('task') }
  const terminate = async () => { await bridge.terminate() }

  return <main className="app-shell">
    <div className="space-grid" />
    <header className="topbar glass-panel">
      <div className="brand"><span className="brand-mark"><Bot size={18} /></span><div><strong>TIA</strong><span>TERMINAL INTELLIGENCE AGENT</span></div></div>
      <div className="top-metrics"><span className={`status status-${snapshot.mode}`}><i /> {statusLabel[snapshot.mode]}</span><span className="metric"><span>ITERATION</span><b>{String(snapshot.iteration).padStart(2, '0')}</b></span><span className="connection"><Wifi size={14} /> {snapshot.backend?.connected ? 'BACKEND ONLINE' : 'BACKEND OFFLINE'}</span></div>
      <div className="top-actions"><button className="cancel-button" title="Cancel the active agent run" onClick={terminate} disabled={!snapshot.backend?.running || snapshot.last_event === 'cancellation_requested'}><OctagonX size={16} /> {snapshot.last_event === 'cancellation_requested' ? 'CANCELLING' : 'CANCEL RUN'}</button><button className="icon-button" title="Settings"><Settings size={17} /></button></div>
    </header>
    <div className="workspace">
      <nav className="rail glass-panel">{nav.map(([id, label, Icon]) => <button key={id} className={`nav-item ${view === id ? 'active' : ''}`} onClick={() => setView(id)} title={label}><Icon size={18} /><span>{label}</span></button>)}</nav>
      <section className="content">
        <div className="section-kicker"><span>LOCAL RUNTIME / SESSION 01</span><span className="rule" /><span>{snapshot.last_event?.replaceAll('_', ' ').toUpperCase() ?? 'STANDBY'}</span></div>
        {view === 'command' && <CommandView goal={goal} setGoal={setGoal} submit={submit} snapshot={snapshot} />}
        {view === 'task' && <TaskView snapshot={snapshot} activeTask={activeTask?.objective} />}
        {view === 'plan' && <PlanPanel plan={plan} />}
        {view === 'concurrent' && <ConcurrentFlowPanel flow={snapshot.concurrent_flow} plan={plan} />}
        {view === 'execution' && <div className="view-stack"><ExecutionPanel workflow={workflow} /><ExecutionAttempts attempts={snapshot.execution_memory} /></div>}
        {view === 'terminal' && <TerminalPanel snapshot={snapshot} />}
        {view === 'memory' && <MemoryPanel snapshot={snapshot} />}
        {view === 'artifacts' && <ArtifactsPanel snapshot={snapshot} />}
        {view === 'activity' && <ActivityPanel snapshot={snapshot} />}
        {view === 'diagnostics' && <Diagnostics snapshot={snapshot} />}
      </section>
    </div>
    <footer className="eventbar glass-panel"><span className="live-dot" /> EVENT STREAM <div className="event-scroll">{snapshot.terminal.slice(-3).map((entry, index) => <span key={`${entry.time}-${index}`}><b>{entry.time}</b> {entry.text}</span>)}</div></footer>
    {offlineNotice && <OfflineDialog onClose={() => setOfflineNotice(false)} />}
  </main>
}

function CommandView({ goal, setGoal, submit, snapshot }: { goal: string; setGoal: (value: string) => void; submit: (event: React.FormEvent) => void; snapshot: RuntimeSnapshot }) { return <div className="command-view"><div className="hero-copy"><div className="eyebrow"><span className="pulse" /> SYSTEM READY / CONTROL SURFACE</div><h1>What should<br /><em>I accomplish?</em></h1><p>Give TIA a goal. The runtime will reason, plan, execute, observe, and adapt.</p></div><form className="command-form glass-panel" onSubmit={submit}><label htmlFor="goal">DIRECTIVE <span>GOAL INPUT</span></label><textarea id="goal" value={goal} onChange={(event) => setGoal(event.target.value)} placeholder="Describe the outcome you need..." rows={3} /><div className="form-bottom"><span><Command size={14} /> SHIFT + ENTER TO EXECUTE</span><button className="primary-button" type="submit">EXECUTE <ChevronRight size={16} /></button></div></form><div className="quick-grid"><Stat label="RUNTIME" value={statusLabel[snapshot.mode]} /><Stat label="CAPABILITIES" value="12 READY" /><Stat label="MEMORY" value={`${snapshot.memory.active.length} ACTIVE`} /></div></div> }
function Stat({ label, value }: { label: string; value: string }) { return <div className="stat"><span>{label}</span><strong>{value}</strong></div> }
function Panel({ title, eyebrow, children, className = '' }: { title: string; eyebrow?: string; children: React.ReactNode; className?: string }) { return <section className={`glass-panel panel ${className}`}><div className="panel-heading"><div>{eyebrow && <span className="panel-eyebrow">{eyebrow}</span>}<h2>{title}</h2></div><span className="corner-mark">+</span></div>{children}</section> }
function TaskView({ snapshot, activeTask }: { snapshot: RuntimeSnapshot; activeTask?: string }) { return <div className="task-layout"><div className="view-stack"><Panel title="Current Task" eyebrow="TASK CONTEXT"><div className="goal-display">{snapshot.goal || 'No active goal. Return to Command to begin.'}</div><div className="task-columns"><div><span className="label">CURRENT OBJECTIVE</span><strong>{activeTask || snapshot.task_plan?.tasks.find((task) => task.status === 'ready')?.objective || 'Awaiting task initialization'}</strong></div><div><span className="label">STRATEGY</span><strong>{snapshot.execution_workflow?.execution_strategy || 'Runtime will determine a strategy.'}</strong></div></div></Panel><div className="split"><PlanPanel plan={snapshot.task_plan} /><DecisionPanel decision={snapshot.decision} /></div><ObservationPanel observation={snapshot.observation} /></div>{snapshot.thinking?.active && <ThinkingPanel thinking={snapshot.thinking} />}</div> }
function ThinkingPanel({ thinking }: { thinking: NonNullable<RuntimeSnapshot['thinking']> }) { return <aside className="thinking-panel glass-panel"><div className="thinking-header"><span className="thinking-orbit"><span /></span><div><span className="panel-eyebrow">LIVE MODEL TRACE</span><h2>Thinking process</h2></div><span className="thinking-live">LIVE</span></div><div className="thinking-model">{thinking.model || 'MODEL STREAM'}<span>{thinking.started_at || 'NOW'}</span></div><div className="thinking-body">{thinking.text || 'Model is preparing its response...'}</div><div className="thinking-footer"><i /> STREAMING TOKENS</div></aside> }
function PlanPanel({ plan }: { plan: RuntimeSnapshot['task_plan'] }) { return <Panel title="Task Plan" eyebrow="AUTHORITATIVE OBJECTIVES"><div className="plan-id">{plan ? `${plan.plan_id} / ${plan.status.toUpperCase()}` : 'NO PLAN MATERIALIZED'}</div>{plan?.tasks.map((task, index) => <div className={`plan-item ${task.status}`} key={task.task_id}><div className="plan-line"><span className="plan-node">{task.status === 'completed' ? '✓' : task.status === 'in_progress' ? '◉' : '○'}</span>{index < plan.tasks.length - 1 && <span className="connector" />}</div><div><strong>{task.objective}</strong><span>{task.status.replaceAll('_', ' ').toUpperCase()}</span></div></div>) || <Empty text="Plan will appear after TIA accepts a goal." />}</Panel> }
const STEP_LABEL: Record<string, string> = { pending: 'PENDING', in_progress: 'EXECUTING', completed: 'DONE', failed: 'FAILED', skipped: 'SKIPPED' }
const STATUS_LABEL: Record<string, string> = { pending: 'PENDING', ready: 'READY', in_progress: 'IN PROGRESS', completed: 'COMPLETED', blocked: 'BLOCKED', failed: 'FAILED', cancelled: 'CANCELLED' }
const STATUS_FILTERS = ['ready', 'in_progress', 'completed', 'failed', 'cancelled'] as const
const KIND_FILTERS = ['all', 'tool', 'worker', 'error'] as const
const ERROR_EVENTS = new Set(['worker_failed', 'worker_cancelled'])
const TOOL_EVENTS = new Set(['workflow_created', 'workflow_step_started', 'tool_started', 'tool_finished'])
function eventKind(event: ConcurrentEvent): 'tool' | 'worker' | 'error' { if (ERROR_EVENTS.has(event.event)) return 'error'; if (event.event === 'tool_finished' && event.success === false) return 'error'; if (TOOL_EVENTS.has(event.event)) return 'tool'; return 'worker' }
function statusCounts(tasks: ConcurrentTask[]) { const counts: Record<string, number> = {}; tasks.forEach((task) => { counts[task.status] = (counts[task.status] ?? 0) + 1 }); return counts }
function EventIcon({ event, success }: { event: string; success: boolean }) { let Icon = GitBranch; if (event === 'tool_started') Icon = Zap; else if (event === 'tool_finished') Icon = success ? CheckCircle2 : XCircle; else if (event === 'workflow_created' || event === 'workflow_step_started') Icon = Layers; else if (event === 'worker_finished' || event === 'worker_reconciled') Icon = CheckCircle2; else if (event === 'worker_failed' || event === 'worker_cancelled') Icon = OctagonX; else if (event === 'worker_started' || event === 'worker_dispatched' || event === 'worker_running') Icon = Activity; return <Icon size={11} /> }
function ConcurrentFlowPanel({ flow, plan }: { flow: RuntimeSnapshot['concurrent_flow']; plan: RuntimeSnapshot['task_plan'] }) {
  const [selected, setSelected] = useState<string | null>(null)
  const [statusFilter, setStatusFilter] = useState<'all' | TaskStatus>('all')
  const [kindFilter, setKindFilter] = useState<(typeof KIND_FILTERS)[number]>('all')
  const [live, setLive] = useState(true)
  const streamRef = useRef<HTMLDivElement | null>(null)
  const events = flow?.events || []
  const planStatus: Record<string, string> = {}
  plan?.tasks.forEach((task) => { planStatus[task.task_id] = task.status })
  const mergedTasks = (flow?.tasks || []).map((task) => planStatus[task.task_id] && task.status !== 'in_progress' ? { ...task, status: planStatus[task.task_id] } : task)
  const counts = statusCounts(mergedTasks)
  const total = mergedTasks.length
  const resolved = mergedTasks.filter((task) => task.status === 'completed' || task.status === 'failed' || task.status === 'cancelled').length
  const filteredTasks = statusFilter === 'all' ? mergedTasks : mergedTasks.filter((task) => task.status === statusFilter)
  const visibleEvents = events.filter((event) => kindFilter === 'all' || eventKind(event) === kindFilter)
  const wave = flow?.wave_status || 'idle'
  useEffect(() => { if (live && streamRef.current) streamRef.current.scrollTop = streamRef.current.scrollHeight }, [live, visibleEvents.length])
  const focusTask = (taskId: string) => { setSelected(taskId); requestAnimationFrame(() => document.getElementById(`worker-card-${taskId}`)?.scrollIntoView({ behavior: 'smooth', block: 'nearest' })) }
  return <div className="concurrent-view">
    <Panel title="Concurrent Flow" eyebrow="DEPENDENCY-AWARE EXECUTION">
      <div className="flow-summary"><Stat label="WAVE" value={wave.toUpperCase()} /><Stat label="WORKERS" value={`${counts['in_progress'] ?? 0} / ${flow?.max_concurrency || 3}`} /><Stat label="RESOLVED" value={`${resolved} / ${total}`} /><Stat label="PLAN" value={flow?.plan_id ? flow.plan_id.slice(0, 8) : 'NONE'} /></div>
      <div className="wave-progress"><div className="wave-progress-track"><div className="wave-progress-fill" style={{ width: `${total ? Math.round((resolved / total) * 100) : 0}%` }} /></div><span>{resolved}/{total} TASKS RESOLVED</span><span className={`wave-state ${wave}`}>{wave === 'reconciling' ? <Loader2 size={11} className="spin" /> : <i />}{wave.toUpperCase()}</span></div>
      <div className="status-pills"><button className={`status-pill all ${statusFilter === 'all' ? 'selected' : ''}`} onClick={() => setStatusFilter('all')}><span>ALL</span><b>{total}</b></button>{STATUS_FILTERS.map((status) => <button key={status} className={`status-pill ${status} ${statusFilter === status ? 'selected' : ''}`} onClick={() => setStatusFilter(statusFilter === status ? 'all' : status)}><span>{STATUS_LABEL[status]}</span><b>{counts[status] ?? 0}</b></button>)}</div>
      <div className="worker-grid">{filteredTasks.length ? filteredTasks.map((task) => <WorkerCard key={task.task_id} task={task} expanded={selected === task.task_id} onToggle={() => setSelected(selected === task.task_id ? null : task.task_id)} events={events.filter((event) => event.task_id === task.task_id)} />) : <Empty text={mergedTasks.length ? 'No tasks match the selected filter.' : 'Parallel workers will appear when TIA admits an execution wave.'} />}</div>
    </Panel>
    <Panel title="Wave Events" eyebrow="LIVE WORKER TELEMETRY">
      <div className="event-toolbar"><div className="event-kinds">{KIND_FILTERS.map((kind) => <button key={kind} className={`event-kind ${kindFilter === kind ? 'selected' : ''}`} onClick={() => setKindFilter(kind)}>{kind === 'all' ? 'ALL' : kind.toUpperCase()}<b>{kind === 'all' ? events.length : visibleEvents.length}</b></button>)}</div><button className={`live-toggle ${live ? 'on' : ''}`} onClick={() => setLive(!live)}>{live ? <Pause size={12} /> : <Play size={12} />}{live ? 'LIVE' : 'PAUSED'}</button></div>
      <div className="wave-events" ref={streamRef}>{visibleEvents.length ? visibleEvents.slice().reverse().map((event, index) => <button className={`wave-event ${eventKind(event)}`} key={`${event.time}-${event.task_id}-${index}`} onClick={() => { if (event.task_id) focusTask(event.task_id) }}><span>{event.time}</span><EventIcon event={event.event} success={event.success !== false} /><strong>{event.event.replaceAll('_', ' ').toUpperCase()}</strong><small>{event.task_id.slice(0, 8)}</small>{event.capability ? <em>{String(event.capability)}</em> : null}</button>) : <Empty text="No worker events have been emitted yet." />}</div>
    </Panel>
  </div>
}
function WorkerCard({ task, expanded, onToggle, events }: { task: ConcurrentTask; expanded: boolean; onToggle: () => void; events: ConcurrentEvent[] }) {
  const active = task.status === 'in_progress' || task.event === 'worker_running' || task.event === 'worker_dispatched' || task.event === 'worker_started' || task.event === 'wave_started'
  const steps = task.workflow?.steps || []
  const runningStep = steps.findIndex((step) => step.status === 'in_progress')
  const doneSteps = steps.filter((step) => step.status === 'completed').length
  const stepSummary = runningStep >= 0 ? `${runningStep + 1}/${steps.length}` : steps.length && doneSteps === steps.length ? `DONE ${doneSteps}/${steps.length}` : `${steps.length} STEPS`
  return <article id={`worker-card-${task.task_id}`} className={`worker-card ${active ? 'active' : task.status} ${expanded ? 'expanded' : ''}`}>
    <div className="worker-accent" />
    <div className="worker-card-head"><span className="worker-pulse" /><span>{task.task_id.slice(0, 8)}</span>{task.workflow_id && <span className="worker-chip">WF {task.workflow_id.slice(0, 6)}</span>}<b>{STATUS_LABEL[task.status] ?? task.status.replaceAll('_', ' ').toUpperCase()}</b></div>
    <h3>{task.objective}</h3>
    <div className="worker-event-line">{task.event ? <><EventIcon event={task.event} success={task.error == null} /><strong>{task.event.replaceAll('_', ' ').toUpperCase()}</strong></> : <strong>ADMITTED TO WAVE</strong>}</div>
    {steps.length ? <div className="step-chips">{steps.slice(0, 8).map((step) => <span key={step.step_id} className={`step-dot ${step.status}`} title={`${STEP_LABEL[step.status] ?? step.status} — ${step.description}`}>{step.capability.slice(0, 6)}</span>)}{steps.length > 8 && <span className="step-more">+{steps.length - 8}</span>}<span className="step-count">{stepSummary}</span></div> : active ? <div className="step-skeleton"><i /><i /><i /><span>PLANNING WORKFLOW…</span></div> : null}
    <div className="worker-meta"><span>DEPENDS <strong>{task.dependencies.length ? task.dependencies.map((dependency) => <code key={dependency}>{dependency.slice(0, 8)}</code>) : 'NONE'}</strong></span><span>STEPS <strong>{steps.length || '—'}</strong></span></div>
    {task.error && <div className="worker-error">{task.error}</div>}
    {expanded && <div className="worker-details">
      <div className="detail-title">WORKFLOW STEPS</div>
      {steps.length ? <div className="step-list">{steps.map((step, index) => <div key={step.step_id} className={`step-row ${step.status}`}><span className="step-idx">{String(index + 1).padStart(2, '0')}</span><div><strong>{step.description}</strong><span>{step.capability} · {STEP_LABEL[step.status] ?? step.status.toUpperCase()}</span></div></div>)}</div> : <div className="detail-empty">Workflow not generated yet.</div>}
      <div className="detail-title">TASK EVENTS</div>
      {events.length ? <div className="task-events">{events.slice(-12).reverse().map((event, index) => <div key={`${event.time}-${index}`} className={`task-event ${eventKind(event)}`}><span>{event.time}</span><EventIcon event={event.event} success={event.success !== false} /><strong>{event.event.replaceAll('_', ' ').toUpperCase()}</strong>{event.capability ? <em>{String(event.capability)}</em> : null}</div>)}</div> : <div className="detail-empty">No task events yet.</div>}
    </div>}
    <div className={`card-toggle ${expanded ? 'open' : ''}`} onClick={onToggle}>{expanded ? 'HIDE DETAILS' : 'SHOW DETAILS'}<ChevronDown size={13} /></div>
  </article>
}
function ExecutionPanel({ workflow }: { workflow: RuntimeSnapshot['execution_workflow'] }) { return <Panel title="Execution Workflow" eyebrow="TACTICAL LAYER"><div className="strategy">{workflow?.execution_strategy || 'No execution workflow active.'}</div>{workflow?.steps.map((step, index) => <div className={`step ${step.status}`} key={step.step_id}><div className="step-index">{String(index + 1).padStart(2, '0')}</div><div><strong>{step.description}</strong><span>{step.capability} <small>{step.status.replaceAll('_', ' ')}</small></span></div></div>) || <Empty text="Execution steps will be exposed by the runtime." />}</Panel> }
function ObservationPanel({ observation }: { observation: RuntimeSnapshot['observation'] }) { return <Panel title="Observation" eyebrow="RESULT PROCESSING"><div className="observation-grid"><div><span className="label">SUMMARY</span><p>{observation?.summary || 'No observation has been produced yet.'}</p></div><div><span className="label">IMPORTANT INFORMATION</span><p>{observation?.important_information || 'Awaiting tool result normalization.'}</p></div><div><span className="label">CONCLUSION</span><p>{observation?.conclusion || 'Awaiting evaluator evidence.'}</p></div></div></Panel> }
function ExecutionAttempts({ attempts }: { attempts?: unknown }) { const source = attempts && typeof attempts === 'object' && !Array.isArray(attempts) && 'attempts' in attempts ? (attempts as { attempts?: unknown[] }).attempts : attempts; const records = (Array.isArray(source) ? source : []).filter((attempt): attempt is Record<string, unknown> => typeof attempt === 'object' && attempt !== null); return <Panel title="Execution Attempts" eyebrow="EXECUTION MEMORY">{records.length ? records.map((attempt, index) => <div className="attempt" key={String(attempt.attempt_id || index)}><strong>ATTEMPT {index + 1}</strong><span>{String(attempt.status || 'recorded').toUpperCase()}</span><small>{String(attempt.error || attempt.outcome || 'Runtime attempt recorded')}</small></div>) : <Empty text="Attempts will appear after the runtime starts execution." />}</Panel> }
function DecisionPanel({ decision }: { decision: RuntimeSnapshot['decision'] }) { return <Panel title="Runtime Decision" eyebrow="CRITIC / REVIEW"><div className="decision"><CircleAlert size={18} /><strong>{decision?.event.replaceAll('_', ' ').toUpperCase() || 'AWAITING EVALUATION'}</strong></div><p>{decision?.rationale || 'The critic decision context will appear after execution review.'}</p>{decision?.evidence.map((item) => <div className="evidence" key={item.observation}><span>{item.source}</span>{item.observation}</div>)}</Panel> }
function TerminalPanel({ snapshot }: { snapshot: RuntimeSnapshot }) { return <Panel title="Terminal Output" eyebrow="EXECUTION STREAM"><div className="terminal-output">{snapshot.terminal.map((entry, index) => <div className={`terminal-line ${entry.kind}`} key={`${entry.time}-${index}`}><span>{entry.time}</span><code>{entry.text}</code></div>)}</div></Panel> }
function MemoryPanel({ snapshot }: { snapshot: RuntimeSnapshot }) { return <div className="triple"><MemoryColumn title="ACTIVE TASK MEMORY" items={snapshot.memory.active} /><MemoryColumn title="THREAD MEMORY" items={snapshot.memory.thread} /><MemoryColumn title="PERSISTENT MEMORY" items={snapshot.memory.persistent} /></div> }
function MemoryColumn({ title, items }: { title: string; items: string[] }) { return <Panel title={title}><ul className="memory-list">{items.map((item) => <li key={item}>{item}</li>)}</ul></Panel> }
function ArtifactsPanel({ snapshot }: { snapshot: RuntimeSnapshot }) { return <Panel title="Artifact Browser" eyebrow="STORED EVIDENCE">{snapshot.artifacts.length ? snapshot.artifacts.map((artifact) => <div className="artifact" key={artifact.artifact_id}><FileCode2 size={18} /><div><strong>{artifact.artifact_type}</strong><span>{artifact.summary}</span><small>{artifact.artifact_id} / {artifact.source}</small></div></div>) : <Empty text="Artifacts created by the result-processing layer will appear here." />}</Panel> }
function ActivityPanel({ snapshot }: { snapshot: RuntimeSnapshot }) { return <Panel title="Activity Stream" eyebrow="RUNTIME EVENTS"><div className="activity-list">{snapshot.terminal.map((entry, index) => <div key={`${entry.time}-${index}`}><span>{entry.time}</span><strong>{entry.text.split('  /  ')[0]}</strong><p>{entry.text.split('  /  ')[1] || 'Runtime signal received.'}</p></div>)}</div></Panel> }
function Diagnostics({ snapshot }: { snapshot: RuntimeSnapshot }) { return <div className="diagnostics"><Panel title="System Diagnostics" eyebrow="AUTHORITATIVE RUNTIME METRICS"><div className="diag-grid"><Stat label="MODE" value={statusLabel[snapshot.mode]} /><Stat label="LAST EVENT" value={snapshot.last_event?.toUpperCase() || 'NONE'} /><Stat label="ITERATION" value={String(snapshot.iteration).padStart(2, '0')} /><Stat label="BRIDGE" value={snapshot.backend?.connected ? 'CONNECTED' : 'OFFLINE'} /></div></Panel><Panel title="Boundary Health"><div className="health"><span><i /> Runtime event channel</span><b>{snapshot.backend?.connected ? 'ONLINE' : 'OFFLINE'}</b></div><div className="health"><span><i /> Python service adapter</span><b className="muted">LIVE</b></div></Panel></div> }
function Empty({ text }: { text: string }) { return <div className="empty">{text}</div> }
function OfflineDialog({ onClose }: { onClose: () => void }) { return <div className="modal-overlay" onClick={onClose}><div className="modal glass-panel" role="dialog" aria-modal="true" onClick={(event) => event.stopPropagation()}><div className="modal-icon"><CircleAlert size={22} /></div><span className="modal-eyebrow">CONNECTION FAULT</span><h2>Backend is offline</h2><p>TIA cannot execute your command because the backend service is not reachable. Restart it with <code>run_tia.ps1</code> and try again once the status bar reads <strong>BACKEND ONLINE</strong>.</p><div className="modal-actions"><button className="primary-button" onClick={onClose}>GOT IT</button></div></div></div> }

const rootHost = globalThis as typeof globalThis & { __tiaRoot?: ReturnType<typeof createRoot> }
const root = rootHost.__tiaRoot ?? (rootHost.__tiaRoot = createRoot(document.getElementById('root')!))
root.render(<App />)
