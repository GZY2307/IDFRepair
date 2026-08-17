"""Version-bound provenance certificates for one missing IDF object."""

from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass
from hashlib import sha256
import json
from pathlib import Path
from typing import Any, Iterable, Sequence

from idfrepair.io.idf import IDFDocument, IDFObject, canonical, parse_idf
from idfrepair.knowledge.idd import IDDSchema


RESOLVER_VERSION = "single_object_superset_v1"


def _sha_file(path: Path) -> str:
    digest = sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def _sha_json(value: Any) -> str:
    payload = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return sha256(payload.encode("utf-8")).hexdigest()


def _semantic_row(obj: IDFObject) -> tuple[str, str, tuple[str, ...]]:
    return (
        canonical(obj.object_type),
        canonical(obj.name),
        tuple(canonical(field.value) for field in obj.fields),
    )


def semantic_multiset(document: IDFDocument) -> Counter[tuple[Any, ...]]:
    return Counter(_semantic_row(obj) for obj in document.objects)


@dataclass(frozen=True, slots=True)
class MissingReference:
    name: str
    reference_lists: tuple[str, ...]
    owner_bindings: tuple[tuple[int, int, str, str], ...]


def unique_missing_reference(
    document: IDFDocument,
    idd: IDDSchema,
) -> MissingReference | None:
    """Return one unresolved explicit IDD object-list identity, if unique."""

    providers: dict[str, list[IDFObject]] = defaultdict(list)
    for obj in document.objects:
        definition = idd.get(obj.object_type)
        if definition is None or not definition.fields or not obj.fields:
            continue
        for reference in definition.fields[0].references:
            providers[canonical(reference)].append(obj)

    missing: list[tuple[str, tuple[str, ...], tuple[int, int, str, str]]] = []
    for obj in document.objects:
        definition = idd.get(obj.object_type)
        if definition is None:
            continue
        for field in obj.fields:
            field_def = definition.field_at(field.index)
            required = tuple(sorted({
                canonical(value)
                for value in (field_def.object_lists if field_def else ())
            }))
            value = field.value.strip()
            if not required or not value:
                continue
            # Implicit registries such as Nodes have no typed provider object.
            if not any(providers.get(reference) for reference in required):
                continue
            available = {
                canonical(provider.name)
                for reference in required
                for provider in providers.get(reference, ())
            }
            if canonical(value) in available:
                continue
            missing.append((
                value,
                required,
                (obj.index, field.index, obj.object_type, field_def.name),
            ))
    identities = {
        (canonical(name), references)
        for name, references, _binding in missing
    }
    if len(identities) != 1:
        return None
    identity = next(iter(identities))
    rows = [
        binding
        for name, references, binding in missing
        if (canonical(name), references) == identity
    ]
    display_names = {
        name for name, references, _binding in missing
        if (canonical(name), references) == identity
    }
    if len(display_names) != 1:
        return None
    return MissingReference(
        name=next(iter(display_names)),
        reference_lists=identity[1],
        owner_bindings=tuple(sorted(rows)),
    )


@dataclass(frozen=True, slots=True)
class ResolvedObject:
    object_type: str
    object_name: str
    fields: tuple[str, ...]
    source_path: str
    source_file_sha256: str
    source_object_sha256: str
    source_version: str
    target_semantic_multiset_sha256: str
    match_evidence: tuple[str, ...]

    def to_metadata(self) -> dict[str, Any]:
        return {
            "resolver_version": RESOLVER_VERSION,
            "object_type": self.object_type,
            "object_name": self.object_name,
            "fields": self.fields,
            "source_path": self.source_path,
            "source_file_sha256": self.source_file_sha256,
            "source_object_sha256": self.source_object_sha256,
            "source_version": self.source_version,
            "target_semantic_multiset_sha256": self.target_semantic_multiset_sha256,
            "unique_match_count": 1,
            "match_evidence": self.match_evidence,
        }


def _source_files(roots: Iterable[Path]) -> tuple[Path, ...]:
    paths: set[Path] = set()
    for raw in roots:
        root = raw.resolve()
        if root.is_file() and root.suffix.casefold() in {".idf", ".imf"}:
            paths.add(root)
        elif root.is_dir():
            paths.update(path.resolve() for path in root.rglob("*.idf") if path.is_file())
            paths.update(path.resolve() for path in root.rglob("*.imf") if path.is_file())
    return tuple(sorted(paths, key=str))


def resolve_single_object_superset(
    faulty_text: str,
    *,
    missing: MissingReference,
    idd: IDDSchema,
    version: str,
    roots: Sequence[Path],
) -> ResolvedObject | None:
    """Find a unique same-version source equal to faulty plus one object."""

    faulty = parse_idf(faulty_text)
    faulty_rows = semantic_multiset(faulty)
    target_version = ".".join(version.split(".")[:2])
    target_digest = _sha_json(sorted(faulty_rows.items(), key=repr))
    matches: list[ResolvedObject] = []
    target_name = canonical(missing.name)
    required = set(missing.reference_lists)
    for path in _source_files(roots):
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
            document = parse_idf(text)
        except (OSError, UnicodeError, ValueError):
            continue
        if ".".join(document.version.split(".")[:2]) != target_version:
            continue
        source_rows = semantic_multiset(document)
        difference = source_rows - faulty_rows
        if sum(difference.values()) != 1 or faulty_rows - source_rows:
            continue
        extra_row = next(iter(difference))
        candidates = [
            obj for obj in document.objects
            if _semantic_row(obj) == extra_row
            and canonical(obj.name) == target_name
        ]
        if len(candidates) != 1:
            continue
        obj = candidates[0]
        definition = idd.get(obj.object_type)
        declared = {
            canonical(value)
            for value in (
                definition.fields[0].references
                if definition is not None and definition.fields else ()
            )
        }
        if not declared.intersection(required):
            continue
        fields = tuple(field.value for field in obj.fields)
        object_sha = _sha_json({
            "object_type": canonical(obj.object_type),
            "fields": tuple(canonical(value) for value in fields),
        })
        matches.append(ResolvedObject(
            object_type=obj.object_type,
            object_name=obj.name,
            fields=fields,
            source_path=str(path),
            source_file_sha256=_sha_file(path),
            source_object_sha256=object_sha,
            source_version=target_version,
            target_semantic_multiset_sha256=target_digest,
            match_evidence=(
                "version_equal",
                "missing_reference_name_equal",
                "object_list_type_compatible",
                "source_equals_faulty_plus_exactly_one_object",
            ),
        ))
    unique = {
        (row.source_path, canonical(row.object_type), row.source_object_sha256): row
        for row in matches
    }
    return next(iter(unique.values())) if len(unique) == 1 else None


__all__ = [
    "MissingReference",
    "RESOLVER_VERSION",
    "ResolvedObject",
    "resolve_single_object_superset",
    "semantic_multiset",
    "unique_missing_reference",
]
