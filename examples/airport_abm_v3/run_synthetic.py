#!/usr/bin/env python3
"""Run the public, geometry-free Airport ABM V3 synthetic fixture."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys


PROJECT_ROOT = Path(__file__).resolve().parents[2]
SRC = PROJECT_ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from idfrepair.analysis.airport_abm.access_graph import build_role_graphs  # noqa: E402
from idfrepair.analysis.airport_abm.agents import AgentPlan, RouteStop  # noqa: E402
from idfrepair.analysis.airport_abm.dwell import DwellSpec  # noqa: E402
from idfrepair.analysis.airport_abm.model import (  # noqa: E402
    AccessEdge,
    AgentClass,
    SpaceNode,
)
from idfrepair.analysis.airport_abm.simulation import simulate_agents  # noqa: E402
from idfrepair.analysis.airport_abm.validation import validate_simulation  # noqa: E402


SCHEMA = "idfrepair.airport-abm-synthetic-fixture.v3"


def _role(value: str) -> AgentClass:
    try:
        return AgentClass(value)
    except ValueError as exc:
        raise ValueError(f"unknown synthetic agent class: {value}") from exc


def run_fixture(path: Path) -> dict[str, object]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if payload.get("schema_version") != SCHEMA:
        raise ValueError("synthetic fixture schema is invalid")

    nodes = tuple(
        SpaceNode(
            name=row["name"],
            function=row["function"],
            region=row["region"],
            is_virtual=bool(row.get("is_virtual", False)),
        )
        for row in payload["nodes"]
    )
    edges = tuple(
        AccessEdge.functional(
            row["from"],
            row["to"],
            {_role(value) for value in row["roles"]},
            row["evidence_ref"],
        )
        for row in payload["edges"]
    )
    graphs = build_role_graphs(nodes, edges)

    plans: list[AgentPlan] = []
    for row in payload["agents"]:
        role = _role(row["class"])
        stops = tuple(
            RouteStop(
                location=stop["location"],
                stage=stop["stage"],
                dwell=DwellSpec(
                    kind="deterministic",
                    minimum=float(stop["dwell_minutes"]),
                    maximum=float(stop["dwell_minutes"]),
                    value=float(stop["dwell_minutes"]),
                ),
            )
            for stop in row["stops"]
        )
        plan = AgentPlan(
            agent_id=row["agent_id"],
            agent_class=role,
            spawn_minute=float(row["spawn_minute"]),
            stops=stops,
            terminal_state=row["terminal_state"],
            deadline_minute=(
                float(row["deadline_minute"])
                if row.get("deadline_minute") is not None
                else None
            ),
        )
        graph = graphs.staff if role is AgentClass.STAFF else graphs.passenger
        expected_path = tuple(stop.location for stop in stops) + (plan.terminal_state,)
        for source, target in zip(expected_path, expected_path[1:]):
            graph.shortest_path(source, target, role)
        plans.append(plan)

    result = simulate_agents(plans, seed=int(payload["seed"]))
    allowed_edges = {
        role: {
            (edge.source, edge.target)
            for edge in edges
            if edge.routable and role in edge.role_set
        }
        for role in AgentClass
    }
    report = validate_simulation(
        result,
        {node.name: node.function for node in nodes},
        allowed_edges,
    )
    return {
        "status": report.status,
        "spawned": result.spawned_count,
        "terminal": result.terminal_count,
        "active": result.active_count,
        "violations": report.violation_count,
        "classes": sorted({plan.agent_class.value for plan in plans}),
        "passenger_graph_edges": len(graphs.passenger.edges),
        "staff_graph_edges": len(graphs.staff.edges),
        "measured_flow_claim": False,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--fixture", required=True)
    args = parser.parse_args()
    summary = run_fixture(Path(args.fixture))
    print(json.dumps(summary, sort_keys=True))
    return 0 if summary["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
