import { useEffect, useState } from 'react'
import { createRoot } from 'react-dom/client'
import { Activity, Archive, Bot, ChevronRight, CircleAlert, Command, Cpu, Database, FileCode2, Layers3, ListChecks, MemoryStick, Settings, TerminalSquare, Wifi } from 'lucide-react'
import { HttpBridge, RuntimeSnapshot } from './bridge'
import './styles.css'

const bridge = new HttpBridge()
const nav = [
  ['command', 'Command', Command], ['task', 'Current Task', Bot], ['plan', 'Plan', ListChecks], ['execution', 'Execution', Layers3], ['terminal', 'Terminal', TerminalSquare], ['memory', 'Memory', MemoryStick], ['artifacts', 'Artifacts', Archive], ['activity', 'Activity', Activity], ['diagnostics', 'Diagnostics', Cpu],
] as const
const statusLabel: Record<RuntimeSnapshot['mode'], string> = { initializing: 'INITIALIZING', planning: 'PLANNING', executing: 'EXECUTING', reviewing: 'REVIEWING', finished: 'COMPLETED', error: 'ERROR' }

function App() {
  const [snapshot, setSnapshot] = useState<RuntimeSnapshot>(bridge.getSnapshot())
  const [view, setView] = useState('command')
  const [goal, setGoal] = useState('')
  useEffect(() => bridge.subscribe(setSnapshot), [])
  const plan = snapshot.task_plan
  const workflow = snapshot.execution_workflow
  const activeTask = plan?.tasks.find((task) => task.status === 'in_progress')
  const submit = async (event: React.FormEvent) => { event.preventDefault(); await bridge.submitGoal(goal); setView('task') }

  return <main className="app-shell">
    <div className="space-grid" />
    <header className="topbar glass-panel">
      <div className="brand"><span className="brand-mark"><Bot size={18} /></span><div><strong>TIA</strong><span>TERMINAL INTELLIGENCE AGENT</span></div></div>
      <div className="top-metrics"><span className={`status status-${snapshot.mode}`}><i /> {statusLabel[snapshot.mode]}</span><span className="metric"><span>ITERATION</span><b>{String(snapshot.iteration).padStart(2, '0')}</b></span><span className="connection"><Wifi size={14} /> {snapshot.backend?.connected ? 'BACKEND ONLINE' : 'BACKEND OFFLINE'}</span></div>
      <button className="icon-button" title="Settings"><Settings size={17} /></button>
    </header>
    <div className="workspace">
      <nav className="rail glass-panel">{nav.map(([id, label, Icon]) => <button key={id} className={`nav-item ${view === id ? 'active' : ''}`} onClick={() => setView(id)} title={label}><Icon size={18} /><span>{label}</span></button>)}</nav>
      <section className="content">
        <div className="section-kicker"><span>LOCAL RUNTIME / SESSION 01</span><span className="rule" /><span>{snapshot.last_event?.replaceAll('_', ' ').toUpperCase() ?? 'STANDBY'}</span></div>
        {view === 'command' && <CommandView goal={goal} setGoal={setGoal} submit={submit} snapshot={snapshot} />}
        {view === 'task' && <TaskView snapshot={snapshot} activeTask={activeTask?.objective} />}
        {view === 'plan' && <PlanPanel plan={plan} />}
        {view === 'execution' && <div className="view-stack"><ExecutionPanel workflow={workflow} /><ExecutionAttempts attempts={snapshot.execution_memory} /></div>}
        {view === 'terminal' && <TerminalPanel snapshot={snapshot} />}
        {view === 'memory' && <MemoryPanel snapshot={snapshot} />}
        {view === 'artifacts' && <ArtifactsPanel snapshot={snapshot} />}
        {view === 'activity' && <ActivityPanel snapshot={snapshot} />}
        {view === 'diagnostics' && <Diagnostics snapshot={snapshot} />}
      </section>
    </div>
    <footer className="eventbar glass-panel"><span className="live-dot" /> EVENT STREAM <div className="event-scroll">{snapshot.terminal.slice(-3).map((entry, index) => <span key={`${entry.time}-${index}`}><b>{entry.time}</b> {entry.text}</span>)}</div></footer>
  </main>
}

function CommandView({ goal, setGoal, submit, snapshot }: { goal: string; setGoal: (value: string) => void; submit: (event: React.FormEvent) => void; snapshot: RuntimeSnapshot }) { return <div className="command-view"><div className="hero-copy"><div className="eyebrow"><span className="pulse" /> SYSTEM READY / CONTROL SURFACE</div><h1>What should<br /><em>I accomplish?</em></h1><p>Give TIA a goal. The runtime will reason, plan, execute, observe, and adapt.</p></div><form className="command-form glass-panel" onSubmit={submit}><label htmlFor="goal">DIRECTIVE <span>GOAL INPUT</span></label><textarea id="goal" value={goal} onChange={(event) => setGoal(event.target.value)} placeholder="Describe the outcome you need..." rows={3} /><div className="form-bottom"><span><Command size={14} /> SHIFT + ENTER TO EXECUTE</span><button className="primary-button" type="submit">EXECUTE <ChevronRight size={16} /></button></div></form><div className="quick-grid"><Stat label="RUNTIME" value={statusLabel[snapshot.mode]} /><Stat label="CAPABILITIES" value="12 READY" /><Stat label="MEMORY" value={`${snapshot.memory.active.length} ACTIVE`} /></div></div> }
function Stat({ label, value }: { label: string; value: string }) { return <div className="stat"><span>{label}</span><strong>{value}</strong></div> }
function Panel({ title, eyebrow, children, className = '' }: { title: string; eyebrow?: string; children: React.ReactNode; className?: string }) { return <section className={`glass-panel panel ${className}`}><div className="panel-heading"><div>{eyebrow && <span className="panel-eyebrow">{eyebrow}</span>}<h2>{title}</h2></div><span className="corner-mark">+</span></div>{children}</section> }
function TaskView({ snapshot, activeTask }: { snapshot: RuntimeSnapshot; activeTask?: string }) { return <div className="task-layout"><div className="view-stack"><Panel title="Current Task" eyebrow="TASK CONTEXT"><div className="goal-display">{snapshot.goal || 'No active goal. Return to Command to begin.'}</div><div className="task-columns"><div><span className="label">CURRENT OBJECTIVE</span><strong>{activeTask || snapshot.task_plan?.tasks.find((task) => task.status === 'ready')?.objective || 'Awaiting task initialization'}</strong></div><div><span className="label">STRATEGY</span><strong>{snapshot.execution_workflow?.execution_strategy || 'Runtime will determine a strategy.'}</strong></div></div></Panel><div className="split"><PlanPanel plan={snapshot.task_plan} /><DecisionPanel decision={snapshot.decision} /></div><ObservationPanel observation={snapshot.observation} /></div>{snapshot.thinking?.active && <ThinkingPanel thinking={snapshot.thinking} />}</div> }
function ThinkingPanel({ thinking }: { thinking: NonNullable<RuntimeSnapshot['thinking']> }) { return <aside className="thinking-panel glass-panel"><div className="thinking-header"><span className="thinking-orbit"><span /></span><div><span className="panel-eyebrow">LIVE MODEL TRACE</span><h2>Thinking process</h2></div><span className="thinking-live">LIVE</span></div><div className="thinking-model">{thinking.model || 'MODEL STREAM'}<span>{thinking.started_at || 'NOW'}</span></div><div className="thinking-body">{thinking.text || 'Model is preparing its response...'}</div><div className="thinking-footer"><i /> STREAMING TOKENS</div></aside> }
function PlanPanel({ plan }: { plan: RuntimeSnapshot['task_plan'] }) { return <Panel title="Task Plan" eyebrow="AUTHORITATIVE OBJECTIVES"><div className="plan-id">{plan ? `${plan.plan_id} / ${plan.status.toUpperCase()}` : 'NO PLAN MATERIALIZED'}</div>{plan?.tasks.map((task, index) => <div className={`plan-item ${task.status}`} key={task.task_id}><div className="plan-line"><span className="plan-node">{task.status === 'completed' ? '✓' : task.status === 'in_progress' ? '◉' : '○'}</span>{index < plan.tasks.length - 1 && <span className="connector" />}</div><div><strong>{task.objective}</strong><span>{task.status.replaceAll('_', ' ').toUpperCase()}</span></div></div>) || <Empty text="Plan will appear after TIA accepts a goal." />}</Panel> }
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

const rootHost = globalThis as typeof globalThis & { __tiaRoot?: ReturnType<typeof createRoot> }
const root = rootHost.__tiaRoot ?? (rootHost.__tiaRoot = createRoot(document.getElementById('root')!))
root.render(<App />)
