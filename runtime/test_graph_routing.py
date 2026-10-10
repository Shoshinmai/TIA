"""Regression tests for terminal runtime graph routing."""

import runtime_graph
from runtime.stages import RuntimeStage


def test_terminal_stages_route_through_output_consistency():
    mapping = runtime_graph.runtime_stage_mapping()

    assert mapping[RuntimeStage.TERMINATE] == "output_consistency"
    assert mapping[RuntimeStage.ERROR] == "output_consistency"


def test_output_consistency_leads_to_output():
    graph = runtime_graph.runtime_graph.get_graph()
    edges = {(edge.source, edge.target) for edge in graph.edges}

    assert ("output_consistency", "output") in edges
    assert ("output", "__end__") in edges
