"""The four things that travel through the pipeline.

A row carries its own history: what it came in as, what it is now, every change
that was made to it and why, and every issue anybody raised against it. Nothing
happens to a row that the row does not know about, which is what makes the
change log complete by construction rather than by discipline.
"""

from __future__ import annotations

from dataclasses import dataclass, field

# Severities an Issue can carry.
REJECT = "reject"  # the row does not go in the clean feed
REVIEW = "review"  # the row goes in the clean feed, marked for a human

# Outcomes a Change can carry.
CHANGED = "changed"  # a value was rewritten into the canonical form
UNRESOLVED = "unresolved"  # a value was read, not understood, and not guessed
DROPPED = "dropped"  # a whole row was removed (deduping)


@dataclass(frozen=True)
class Change:
    """One edit, or one refusal to edit, attributable to one rule.

    `before` and `after` are always the literal strings, so the log can be read
    without the tool. An UNRESOLVED change has an empty `after` on purpose: the
    canonical column stays empty rather than taking a guess, and `before` is
    where the original survives.
    """

    line: int
    sku: str
    field: str
    rule: str
    before: str
    after: str
    outcome: str = CHANGED
    note: str = ""


@dataclass(frozen=True)
class Issue:
    """Something wrong with a row, in the words you would use to a supplier."""

    rule: str
    field: str
    message: str
    severity: str = REVIEW

    def __str__(self) -> str:
        return f"{self.field}: {self.message}" if self.field else self.message


@dataclass
class Row:
    """One line of the input feed, on its way to being one line of the output."""

    line: int
    raw: dict[str, str]
    extra: dict[str, str] = field(default_factory=dict)
    # The supplier's own headers and their untouched values. Kept so a rejected
    # row can be handed back exactly as it arrived: a rejects file you have to
    # translate before you can fix it is a rejects file nobody fixes.
    original: dict[str, str] = field(default_factory=dict)
    values: dict[str, object] = field(default_factory=dict)
    changes: list[Change] = field(default_factory=list)
    issues: list[Issue] = field(default_factory=list)

    @property
    def sku(self) -> str:
        value = self.values.get("sku")
        if isinstance(value, str) and value:
            return value
        return (self.raw.get("sku") or "").strip()

    @property
    def rejected(self) -> bool:
        return any(issue.severity == REJECT for issue in self.issues)

    @property
    def needs_review(self) -> bool:
        return any(issue.severity == REVIEW for issue in self.issues)

    def get(self, name: str) -> str:
        """The normalized value as a string, or "" — what the writers want."""
        value = self.values.get(name)
        return "" if value is None else str(value)

    def record(
        self,
        field_name: str,
        rule: str,
        before: str,
        after: str,
        outcome: str = CHANGED,
        note: str = "",
    ) -> None:
        self.changes.append(
            Change(
                line=self.line,
                sku=self.sku,
                field=field_name,
                rule=rule,
                before=before,
                after=after,
                outcome=outcome,
                note=note,
            )
        )

    def flag(self, rule: str, field_name: str, message: str, severity: str = REVIEW) -> None:
        issue = Issue(rule=rule, field=field_name, message=message, severity=severity)
        if issue not in self.issues:
            self.issues.append(issue)

    def issue_text(self) -> str:
        return "; ".join(str(issue) for issue in self.issues)

    def rules(self, severity: str | None = None) -> list[str]:
        return [i.rule for i in self.issues if severity is None or i.severity == severity]
