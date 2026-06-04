"""
WorkflowPlan — verbindet ProjectTemplate mit BitwigExecutor.

Verantwortlichkeit:
  - Hält geordnete BitwigStep-Liste
  - Konvertiert zu BitwigResult (→ execute_setup)
  - Koordiniert Ausführung (execute)
  - Wird in Neo4j als Workflow + WorkflowStep Nodes gespeichert

Verwendung:
  plan = WorkflowPlan.from_template(tmpl, current_snapshot)
  WorkflowRepository().save(plan)
  plan.execute()
"""
from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from typing import Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from src.agent.models.project_template import ProjectTemplate
    from src.agent.models.project_snapshot import BitwigProjectSnapshot
    from src.agent.models.steps import BitwigStep


@dataclass
class WorkflowPlan:
    steps: list["BitwigStep"]
    context: str = ""                   # Beschreibung des Ziels
    project_name: str = ""
    template_name: str = ""
    workflow_id: str = field(default_factory=lambda: str(uuid.uuid4())[:8])
    created_at: float = field(default_factory=time.time)

    # ── Factory ────────────────────────────────────────────────────────────────

    @classmethod
    def from_template(cls,
                      template: "ProjectTemplate",
                      current: Optional["BitwigProjectSnapshot"] = None,
                      context: str = "") -> "WorkflowPlan":
        """Baut WorkflowPlan aus Template — diff gegen aktuellen State."""
        steps = template.to_steps(current)
        return cls(
            steps=steps,
            context=context or f"Erstelle {template.name}",
            project_name=template.name,
            template_name=template.name,
        )

    @classmethod
    def from_steps(cls, steps: list["BitwigStep"], context: str = "") -> "WorkflowPlan":
        """Direkt aus Step-Liste (für Backward-Compat mit BitwigResultBuilder)."""
        return cls(steps=steps, context=context)

    # ── Konvertierung ──────────────────────────────────────────────────────────

    def to_result(self) -> dict:
        """Konvertiert zu BitwigResult-kompatiblem dict → execute_setup."""
        from src.agent.models.result import BitwigResult
        result = BitwigResult(
            context_type="song",
            target={"project": self.project_name},
            summary=self.context,
            steps=self.steps,
        )
        return result.to_dict()

    # ── Ausführung ─────────────────────────────────────────────────────────────

    def execute(self) -> str:
        """Führt den Plan via BitwigExecutor aus. Gibt Status-String zurück."""
        from src.bitwig_executor import execute_setup
        return execute_setup(self.to_result())

    # ── MLX-Kontext für Validierung ────────────────────────────────────────────

    def validation_context(self, snapshot: Optional["BitwigProjectSnapshot"] = None) -> dict:
        """Reichert MLX/Ollama Payload mit Projekt-Kontext an."""
        ctx: dict = {
            "project": self.project_name,
            "template": self.template_name,
            "step_count": len(self.steps),
        }
        if snapshot:
            ctx["tempo"] = snapshot.tempo
            ctx["scenes"] = [s.name for s in snapshot.scenes]
            ctx["tracks"] = [
                {"name": t.name, "role": t.role, "instrument": t.instrument}
                for t in snapshot.instrument_tracks()[:8]
            ]
        return ctx

    def __repr__(self) -> str:
        return (
            f"WorkflowPlan({self.workflow_id}, "
            f"{len(self.steps)} steps, "
            f"context={self.context!r})"
        )
