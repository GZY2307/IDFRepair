"""Version-bound RDD output-variable catalog."""

from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
import re

from idfrepair.io.idf import canonical


_UNITS = re.compile(r"\s*\[[^\]]*\]\s*$")
_TOKENS = re.compile(r"[a-z0-9]+")
_OPPOSED_TERMS = (
    frozenset({"heating", "cooling"}),
    frozenset({"rate", "energy"}),
    frozenset({"pmv", "ppd"}),
)


@dataclass(frozen=True, slots=True)
class RDDCatalog:
    text: str
    variable_names: tuple[str, ...]
    meter_names: tuple[str, ...]

    @property
    def sha256(self) -> str:
        return sha256(self.text.encode("utf-8")).hexdigest()

    def contains(self, value: str) -> bool:
        key = canonical(value)
        return any(canonical(name) == key for name in self.variable_names + self.meter_names)


def parse_rdd(text: str) -> RDDCatalog:
    variables: dict[str, str] = {}
    meters: dict[str, str] = {}
    for raw in text.splitlines():
        line = raw.split("!", 1)[0].strip().rstrip(";")
        if not line:
            continue
        parts = [part.strip() for part in line.split(",")]
        if len(parts) < 2:
            continue
        first = canonical(parts[0])
        name = ""
        target = variables
        if first == "output:variable" and len(parts) >= 3:
            name = parts[2]
        elif first == "output:meter" and len(parts) >= 2:
            name = parts[-1]
            target = meters
        elif len(parts) >= 3 and canonical(parts[1]) in {"average", "sum"}:
            name = parts[2]
        name = _UNITS.sub("", name).strip()
        if name:
            target.setdefault(canonical(name), name)
    return RDDCatalog(
        text=text,
        variable_names=tuple(variables[key] for key in sorted(variables)),
        meter_names=tuple(meters[key] for key in sorted(meters)),
    )


def _distance(left: str, right: str) -> int:
    previous = list(range(len(right) + 1))
    for row_index, left_char in enumerate(left, start=1):
        current = [row_index]
        for column, right_char in enumerate(right, start=1):
            current.append(min(
                current[-1] + 1,
                previous[column] + 1,
                previous[column - 1] + int(left_char != right_char),
            ))
        previous = current
    return previous[-1]


def _normalized(value: str) -> str:
    return "".join(_TOKENS.findall(value.casefold()))


def unique_variable_match(faulty: str, choices: tuple[str, ...]) -> tuple[str, int] | None:
    """Return one bounded typo match with semantic-opposition exclusion."""

    source = _normalized(faulty)
    scored = sorted((_distance(source, _normalized(choice)), canonical(choice), choice) for choice in choices)
    if not scored:
        return None
    distance = scored[0][0]
    best = [row for row in scored if row[0] == distance]
    if distance < 1 or distance > (2 if len(source) >= 8 else 1) or len(best) != 1:
        return None
    proposed = best[0][2]
    proposed_tokens = set(_TOKENS.findall(proposed.casefold()))
    faulty_tokens = set(_TOKENS.findall(faulty.casefold()))
    for pair in _OPPOSED_TERMS:
        selected = proposed_tokens & pair
        if len(selected) != 1 or faulty_tokens & pair:
            continue
        counterpart = next(iter(pair - selected))
        base = proposed_tokens - pair
        if any(
            set(_TOKENS.findall(choice.casefold())) - pair == base
            and counterpart in set(_TOKENS.findall(choice.casefold()))
            and _distance(source, _normalized(choice)) <= distance + 1
            for choice in choices
        ):
            return None
    return proposed, distance


__all__ = ["RDDCatalog", "parse_rdd", "unique_variable_match"]
