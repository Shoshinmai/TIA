export type RuntimeMode = 'initializing' | 'planning' | 'executing' | 'reviewing' | 'finished' | 'error'
export type TaskStatus = 'pending' | 'ready' | 'in_progress' | 'completed' | 'blocked' | 'failed' | 'cancelled'
export type StepStatus = 'pending' | 'in_progress' | 'completed' | 'failed' | 'skipped'

export interface TaskItem { task_id: string; objective: string; status: TaskStatus; dependencies: string[] }
export interface TaskPlan { plan_id: string; goal: string; status: string; tasks: TaskItem[] }
export interface ExecutionStep { step_id: string; description: string; capability: string; arguments: Record<string, unknown>; status: StepStatus }
export interface ExecutionWorkflow { workflow_id: string; objective: string; execution_strategy: string; status: string; steps: ExecutionStep[] }
export interface DecisionContext { event: string; rationale: string; evidence: { source: string; observation: string }[] }
export interface Artifact { artifact_id: string; artifact_type: string; summary: string; source: string }
export interface MemoryState { active: string[]; thread: string[]; persistent: string[] }
export interface ObservationState { summary: string; important_information: string; conclusion: string; raw: unknown }
export interface ThinkingState { active: boolean; model: string; text: string; started_at: string | null }
export interface ConcurrentTask { task_id: string; objective: string; status: string; dependencies: string[]; blockers?: string[]; event?: string; error?: string; workflow_id?: string; workflow?: ExecutionWorkflow | null }
export interface ConcurrentEvent { time: string; task_id: string; event: string; [key: string]: unknown }
export interface ConcurrentFlow { plan_id: string | null; wave_status: string; max_concurrency: number; tasks: ConcurrentTask[]; events: ConcurrentEvent[] }
export interface RuntimeSnapshot {
  mode: RuntimeMode
  last_event: string | null
  iteration: number
  goal: string
  task_plan: TaskPlan | null
  execution_workflow: ExecutionWorkflow | null
  terminal: { time: string; kind: 'system' | 'command' | 'success' | 'error'; text: string }[]
  decision: DecisionContext | null
  artifacts: Artifact[]
  memory: MemoryState
  observation?: ObservationState
  execution_memory?: unknown
  thinking?: ThinkingState
  concurrent_flow?: ConcurrentFlow
  backend?: { connected: boolean; running: boolean; error: string | null }
}

export interface TiaBridge {
  getSnapshot(): RuntimeSnapshot
  submitGoal(goal: string): Promise<void>
  terminate(): Promise<boolean>
  subscribe(listener: (snapshot: RuntimeSnapshot) => void): () => void
  dispose(): void
}

const API_URL = import.meta.env.VITE_TIA_API_URL || ''
const stamp = () => new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' })

const emptySnapshot = (): RuntimeSnapshot => ({
  mode: 'initializing', last_event: null, iteration: 0, goal: '', task_plan: null, execution_workflow: null,
  terminal: [{ time: stamp(), kind: 'system', text: 'Backend bridge ready. Awaiting a runtime task.' }], decision: null, artifacts: [],
  memory: { active: [], thread: [], persistent: [] },
  backend: { connected: false, running: false, error: null },
  thinking: { active: false, model: '', text: '', started_at: null },
  concurrent_flow: { plan_id: null, wave_status: 'idle', max_concurrency: 3, tasks: [], events: [] },
})

export class HttpBridge implements TiaBridge {
  private listeners = new Set<(snapshot: RuntimeSnapshot) => void>()
  private snapshot = emptySnapshot()
  private events: EventSource | null = null
  private taskId: string | null = null
  private disposed = false
  private healthTimer: number | null = null

  constructor() {
    void this.checkHealth()
    this.healthTimer = window.setInterval(() => {
      if (this.disposed) return
      if (!this.snapshot.backend?.connected) void this.checkHealth()
    }, 5000)
  }

  getSnapshot() { return this.snapshot }
  subscribe(listener: (snapshot: RuntimeSnapshot) => void) { this.listeners.add(listener); listener(this.snapshot); return () => { this.listeners.delete(listener) } }
  dispose() { this.disposed = true; if (this.healthTimer !== null) window.clearInterval(this.healthTimer); this.events?.close(); this.listeners.clear() }
  private publish(snapshot: RuntimeSnapshot) { if (this.disposed) return; this.snapshot = snapshot; this.listeners.forEach((listener) => listener(this.snapshot)) }

  private appendLine(terminal: RuntimeSnapshot['terminal'], kind: RuntimeSnapshot['terminal'][number]['kind'], text: string) {
    const entry = { time: stamp(), kind, text }
    if (terminal[terminal.length - 1]?.text === text) return terminal
    return [...terminal, entry].slice(-80)
  }

  private async checkHealth() {
    try {
      const response = await fetch(`${API_URL}/health`)
      if (!response.ok) throw new Error(`Health check failed (${response.status})`)
      this.publish({
        ...this.snapshot,
        backend: { connected: true, running: false, error: null },
        terminal: this.appendLine(this.snapshot.terminal, 'system', 'Backend connected. Ready for a runtime task.'),
      })
    } catch {
      this.publish({ ...this.snapshot, backend: { connected: false, running: false, error: 'TIA backend is not reachable' } })
    }
  }

  async submitGoal(goal: string) {
    if (!goal.trim()) return
    this.events?.close()
    try {
      const response = await fetch(`${API_URL}/api/tasks`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ goal }) })
      if (!response.ok) throw new Error(`Backend rejected the task (${response.status})`)
      const result = await response.json() as { task_id: string; snapshot: RuntimeSnapshot }
      this.taskId = result.task_id
      this.publish(result.snapshot)
      this.events = new EventSource(`${API_URL}/api/tasks/${this.taskId}/events`)
      this.events.onmessage = (event) => {
        const snapshot = JSON.parse(event.data) as RuntimeSnapshot
        this.publish(snapshot)
        if (snapshot.mode === 'finished' || snapshot.mode === 'error') {
          this.events?.close()
          this.events = null
        }
      }
      this.events.onerror = () => {
        if (this.events?.readyState === EventSource.CLOSED) return
        this.events?.close()
        this.events = null
        this.publish({ ...this.snapshot, mode: 'error', last_event: 'backend_disconnected', terminal: [...this.snapshot.terminal, { time: stamp(), kind: 'error', text: 'BACKEND_DISCONNECTED  /  Event stream closed' }] })
      }
    } catch (error) {
      this.publish({ ...this.snapshot, mode: 'error', last_event: 'task_failed', terminal: [...this.snapshot.terminal, { time: stamp(), kind: 'error', text: `BACKEND_ERROR  /  ${error instanceof Error ? error.message : 'Unable to reach TIA backend'}` }] })
    }
  }

  async terminate() {
    if (!this.taskId || !this.snapshot.backend?.running) return false
    try {
      const response = await fetch(`${API_URL}/api/tasks/${this.taskId}/terminate`, { method: 'POST' })
      if (!response.ok) throw new Error(`Cancellation was rejected (${response.status})`)
      this.publish({ ...this.snapshot, last_event: 'cancellation_requested', backend: { connected: true, running: true, error: null }, terminal: [...this.snapshot.terminal, { time: stamp(), kind: 'system', text: 'CANCELLATION_REQUESTED  /  Stopping agent run...' }] })
      return true
    } catch (error) {
      this.publish({ ...this.snapshot, mode: 'error', last_event: 'terminate_failed', backend: { connected: false, running: false, error: error instanceof Error ? error.message : 'Unable to terminate task' } })
      return false
    }
  }
}
