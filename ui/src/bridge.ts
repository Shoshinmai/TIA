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
  backend?: { connected: boolean; running: boolean; error: string | null }
}

export interface TiaBridge {
  getSnapshot(): RuntimeSnapshot
  submitGoal(goal: string): Promise<void>
  subscribe(listener: (snapshot: RuntimeSnapshot) => void): () => void
  dispose(): void
}

const API_URL = import.meta.env.VITE_TIA_API_URL || 'http://127.0.0.1:8787'
const stamp = () => new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' })

const emptySnapshot = (): RuntimeSnapshot => ({
  mode: 'initializing', last_event: null, iteration: 0, goal: '', task_plan: null, execution_workflow: null,
  terminal: [{ time: stamp(), kind: 'system', text: 'Backend bridge ready. Awaiting a runtime task.' }], decision: null, artifacts: [],
  memory: { active: [], thread: [], persistent: [] },
  backend: { connected: false, running: false, error: null },
  thinking: { active: false, model: '', text: '', started_at: null },
})

export class HttpBridge implements TiaBridge {
  private listeners = new Set<(snapshot: RuntimeSnapshot) => void>()
  private snapshot = emptySnapshot()
  private events: EventSource | null = null
  private taskId: string | null = null
  private disposed = false

  constructor() {
    void this.checkHealth()
  }

  getSnapshot() { return this.snapshot }
  subscribe(listener: (snapshot: RuntimeSnapshot) => void) { this.listeners.add(listener); listener(this.snapshot); return () => { this.listeners.delete(listener) } }
  dispose() { this.disposed = true; this.events?.close(); this.listeners.clear() }
  private publish(snapshot: RuntimeSnapshot) { if (this.disposed) return; this.snapshot = snapshot; this.listeners.forEach((listener) => listener(this.snapshot)) }

  private async checkHealth() {
    try {
      const response = await fetch(`${API_URL}/health`)
      if (!response.ok) throw new Error(`Health check failed (${response.status})`)
      this.publish({ ...this.snapshot, backend: { connected: true, running: false, error: null }, terminal: [{ time: stamp(), kind: 'system', text: 'Backend connected. Ready for a runtime task.' }] })
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
      this.events.onmessage = (event) => this.publish(JSON.parse(event.data) as RuntimeSnapshot)
      this.events.onerror = () => this.publish({ ...this.snapshot, mode: 'error', last_event: 'backend_disconnected', terminal: [...this.snapshot.terminal, { time: stamp(), kind: 'error', text: 'BACKEND_DISCONNECTED  /  Event stream closed' }] })
    } catch (error) {
      this.publish({ ...this.snapshot, mode: 'error', last_event: 'task_failed', terminal: [...this.snapshot.terminal, { time: stamp(), kind: 'error', text: `BACKEND_ERROR  /  ${error instanceof Error ? error.message : 'Unable to reach TIA backend'}` }] })
    }
  }
}
