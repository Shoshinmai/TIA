from runtime.agentic_loop_context import build_agentic_loop_context

state = {'goal': 'Inspect the project and report the result.'}
try:
    ctx = build_agentic_loop_context(state, capabilities=[], observations=())
    print('Goal:', ctx.goal)
    print('Loop context preview:', ctx.loop_context[:100] if ctx.loop_context else 'empty')
    print('Capabilities preview:', ctx.available_capabilities[:100] if ctx.available_capabilities else 'empty')
    print('Observations:', ctx.observations)
except Exception as e:
    print('Error:', type(e).__name__, e)