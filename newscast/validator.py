"""validate_show() -- the eval harness for everything downstream (§10).

Every generated script runs through this, and the violation rate is the primary
quality metric, so the report carries counts as well as the violations.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from newscast.config import ShowConfig
from newscast.model import Show
from newscast.rules import Rule, Severity, Violation, all_rules
from newscast.timing import block_seconds, story_seconds


@dataclass
class ValidationReport:
    violations: list[Violation] = field(default_factory=list)
    story_count: int = 0
    rules_run: list[str] = field(default_factory=list)

    def by_severity(self, severity: Severity) -> list[Violation]:
        return [v for v in self.violations if v.severity is severity]

    @property
    def errors(self) -> list[Violation]:
        return self.by_severity(Severity.ERROR)

    @property
    def warnings(self) -> list[Violation]:
        return self.by_severity(Severity.WARNING)

    @property
    def infos(self) -> list[Violation]:
        return self.by_severity(Severity.INFO)

    @property
    def ok(self) -> bool:
        """True when nothing would break on air."""
        return not self.errors

    @property
    def violation_rate(self) -> float:
        """Errors + warnings per story -- the §10 quality metric."""
        if not self.story_count:
            return 0.0
        counted = len(self.errors) + len(self.warnings)
        return round(counted / self.story_count, 3)

    def codes(self) -> dict[str, int]:
        out: dict[str, int] = {}
        for v in self.violations:
            out[v.code] = out.get(v.code, 0) + 1
        return dict(sorted(out.items()))

    def format(self, show_info: bool = True) -> str:
        lines: list[str] = []
        for severity in (Severity.ERROR, Severity.WARNING, Severity.INFO):
            if severity is Severity.INFO and not show_info:
                continue
            for v in self.by_severity(severity):
                lines.append(str(v))
        lines.append(
            f"\n{len(self.errors)} error(s), {len(self.warnings)} warning(s), "
            f"{len(self.infos)} info across {self.story_count} stories "
            f"(violation rate {self.violation_rate})"
        )
        return "\n".join(lines)


def _sort_key(v: Violation) -> tuple:
    return (-int(v.severity), v.block, v.line_no, v.code)


def validate_show(
    show: Show,
    config: ShowConfig | None = None,
    only: list[str] | None = None,
) -> ValidationReport:
    """Run the §5 rule engine over an assembled rundown."""
    config = config or ShowConfig()
    rules: list[Rule] = [r for r in all_rules() if not only or r.code in only]

    violations: list[Violation] = []
    for r in rules:
        violations.extend(r.fn(show, config))

    return ValidationReport(
        violations=sorted(violations, key=_sort_key),
        story_count=len(list(show.stories)),
        rules_run=[r.code for r in rules],
    )


def show_summary(show: Show, config: ShowConfig | None = None) -> str:
    """Human-readable rundown with timings -- useful when eyeballing a fill."""
    config = config or ShowConfig()
    lines: list[str] = []
    total = 0.0
    for block in show.blocks:
        seconds = block_seconds(block, config)
        total += seconds
        lines.append(f"=== HALF {block.half} BLOCK {block.label} ({seconds:.1f}s) ===")
        for i, story in enumerate(block.stories):
            mark = "*" if story.accepted else " "
            lines.append(
                f" {mark} {i + 1:>2}. {story.slug or '(unslugged)':<34} "
                f"{story.form:<12} {story_seconds(story, config):>6.1f}s"
            )
    lines.append(f"total {total:.1f}s")
    return "\n".join(lines)
