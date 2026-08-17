"""Bind parser cascades to uniquely provable delimiter defects."""

from __future__ import annotations

from dataclasses import dataclass
import re

from idfrepair.io.idf import IDFDocument, IDFObject, parse_idf
from idfrepair.knowledge.idd import IDDSchema
from idfrepair.validation.geometry import validate_polygon


_ERROR_PARSING = re.compile(r'Error parsing "(?P<object>[^"]+)"', re.I)
_SCHEDULE_UNTIL = re.compile(
    r"\bUntil\s*:\s*(?:[01]?\d|2[0-4]):[0-5]\d(?=\s*[+\-]?(?:\d|\.\d))",
    re.I,
)
_NUMBER = re.compile(
    r"[+\-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[Ee][+\-]?\d+)?"
)


@dataclass(frozen=True, slots=True)
class SyntaxSite:
    kind: str
    delimiter: str
    offset: int
    line_number: int
    object_index: int | None
    object_type: str
    next_object_type: str | None
    evidence: str


def _code(line: str) -> str:
    return line.split("!", 1)[0].rstrip("\r\n").rstrip()


def _line_rows(text: str) -> list[tuple[int, str]]:
    rows: list[tuple[int, str]] = []
    offset = 0
    for line in text.splitlines(keepends=True):
        rows.append((offset, line))
        offset += len(line)
    if not rows or offset < len(text):
        rows.append((offset, text[offset:]))
    return rows


def _next_significant(rows: list[tuple[int, str]], start: int) -> int | None:
    return next((index for index in range(start, len(rows)) if _code(rows[index][1]).strip()), None)


def _containing_object(document: IDFDocument, offset: int) -> IDFObject | None:
    return next((obj for obj in document.objects if obj.start <= offset < obj.end), None)


def _insert(text: str, offset: int, delimiter: str) -> str:
    return text[:offset] + delimiter + text[offset:]


def _reparse_containing_object(
    document: IDFDocument,
    obj: IDFObject,
    offset: int,
    delimiter: str,
) -> IDFObject | None:
    '''Reparse one object for an insertion that cannot affect neighboring objects.'''
    if not obj.start <= offset <= obj.end:
        return None
    code_start = obj.start
    in_comment = False
    for position in range(obj.start, obj.end):
        character = document.text[position]
        if in_comment:
            if character in "\r\n":
                in_comment = False
            continue
        if character == "!":
            in_comment = True
            continue
        if character in ",;":
            code_start = _visible_code_start(document.text, obj.start, position)
            break
    fragment = document.text[code_start:obj.end]
    proposed = parse_idf(_insert(fragment, offset - code_start, delimiter))
    if len(proposed.objects) != 1:
        return None
    repaired = proposed.objects[0]
    if repaired.object_type.casefold() != obj.object_type.casefold():
        return None
    return repaired


def _visible_code_start(text: str, start: int, end: int) -> int:
    '''Return the first non-comment, non-whitespace code offset in a span.'''
    in_comment = False
    for position in range(start, end):
        character = text[position]
        if in_comment:
            if character in "\r\n":
                in_comment = False
            continue
        if character == "!":
            in_comment = True
            continue
        if not character.isspace():
            return position
    return start


def _missing_comma_sites(document: IDFDocument, idd: IDDSchema) -> list[SyntaxSite]:
    rows = _line_rows(document.text)
    sites: list[SyntaxSite] = []
    for line_index, (line_start, line) in enumerate(rows):
        if "!-" not in line:
            continue
        code = _code(line)
        token = code.strip()
        if not token or token.endswith((",", ";")):
            continue
        next_index = _next_significant(rows, line_index + 1)
        if next_index is None:
            continue
        offset = line_start + len(code)
        obj = _containing_object(document, offset)
        if obj is None:
            continue
        definition = idd.get(obj.object_type)
        if definition is None:
            continue
        repaired = _reparse_containing_object(document, obj, offset, ",")
        if repaired is None:
            continue
        if len(repaired.fields) != len(obj.fields) + 1:
            continue
        if definition.maximum_fields is not None and len(repaired.fields) > definition.maximum_fields:
            continue
        sites.append(SyntaxSite(
            kind="missing_comma",
            delimiter=",",
            offset=offset,
            line_number=line_index + 1,
            object_index=obj.index,
            object_type=obj.object_type,
            next_object_type=None,
            evidence="annotated_field_boundary_and_current_idd",
        ))
    return sites


def _blank_annotated_comma_sites(
    document: IDFDocument,
    idd: IDDSchema,
) -> list[SyntaxSite]:
    '''用相邻注释字段的一致缩进定位被删除的空字段逗号。'''
    rows = _line_rows(document.text)
    sites = []
    for line_index, (line_start, line) in enumerate(rows):
        if "!-" not in line or _code(line).strip():
            continue
        neighbor_indents = []
        for direction in (-1, 1):
            index = line_index + direction
            while 0 <= index < len(rows):
                candidate = rows[index][1]
                code = _code(candidate)
                if "!-" in candidate and code.strip():
                    neighbor_indents.append(len(code) - len(code.lstrip()))
                    break
                if code.strip() and "!-" not in candidate:
                    break
                index += direction
        if not neighbor_indents or len(set(neighbor_indents)) != 1:
            continue
        offset = line_start + neighbor_indents[0]
        obj = _containing_object(document, offset)
        if obj is None:
            continue
        definition = idd.get(obj.object_type)
        if definition is None:
            continue
        repaired = _reparse_containing_object(document, obj, offset, ",")
        if repaired is None:
            continue
        if len(repaired.fields) != len(obj.fields) + 1:
            continue
        if definition.maximum_fields is not None and len(repaired.fields) > definition.maximum_fields:
            continue
        sites.append(SyntaxSite(
            kind="missing_blank_comma",
            delimiter=",",
            offset=offset,
            line_number=line_index + 1,
            object_index=obj.index,
            object_type=obj.object_type,
            next_object_type=None,
            evidence="blank_annotated_field_and_neighbor_indent",
        ))
    return sites


def _schedule_compact_sites(
    document: IDFDocument,
    idd: IDDSchema,
) -> list[SyntaxSite]:
    '''恢复 Schedule:Compact 的 Until HH:MM 与值之间唯一逗号。'''
    sites = []
    for obj in document.objects:
        if obj.object_type.casefold() != "schedule:compact":
            continue
        fragment = document.text[obj.start:obj.end]
        for match in _SCHEDULE_UNTIL.finditer(fragment):
            offset = obj.start + match.end()
            proposed = parse_idf(_insert(document.text, offset, ","))
            if len(proposed.objects) != len(document.objects) or obj.index >= len(proposed.objects):
                continue
            repaired = proposed.objects[obj.index]
            if len(repaired.fields) != len(obj.fields) + 1:
                continue
            definition = idd.get(obj.object_type)
            if definition is None or definition.field_at(len(repaired.fields)) is None:
                continue
            sites.append(SyntaxSite(
                kind="schedule_compact_until_comma",
                delimiter=",",
                offset=offset,
                line_number=document.text.count("\n", 0, offset) + 1,
                object_index=obj.index,
                object_type=obj.object_type,
                next_object_type=None,
                evidence="schedule_compact_until_grammar",
            ))
    return sites


def _numeric_signature(value: str) -> tuple[bool, int, bool]:
    '''返回科学记数、尾数小数位和省略前导零三项格式身份。'''
    lowered = value.casefold()
    mantissa = lowered.split("e", 1)[0]
    decimals = len(mantissa.split(".", 1)[1]) if "." in mantissa else -1
    return "e" in lowered, decimals, mantissa.startswith(('.', '+.', '-.'))


def _numeric_fragment_weird(value: str) -> bool:
    '''Reject split-only numeric spellings with omitted or redundant leading zero.'''
    lowered = value.casefold().lstrip("+-")
    mantissa = lowered.split("e", 1)[0]
    integer = mantissa.split(".", 1)[0]
    return bool(
        mantissa.startswith(".")
        or (len(integer) > 1 and integer.startswith("0"))
    )


def _numeric_role(name: str) -> str:
    '''移除 extensible 序号，使同一坐标轴或字段角色可比较。'''
    return re.sub(r"\d+", "#", name.casefold())


def _split_score(repaired: IDFObject, definition, index: int) -> tuple[int, int, int]:  # type: ignore[no-untyped-def]
    '''按同角色表示格式和值重复证据对一个数字拆分评分。'''
    format_matches = 0
    value_matches = 0
    weird = 0
    targets = {index, index + 1}
    for target_index in targets:
        target = repaired.fields[target_index - 1]
        field_def = definition.field_at(target_index)
        if field_def is None:
            continue
        signature = _numeric_signature(target.value)
        weird += int(
            signature[2]
            or _numeric_fragment_weird(target.value)
            or target.value in {"+", "-"}
        )
        role = _numeric_role(field_def.name)
        try:
            target_number = float(target.value)
        except ValueError:
            continue
        for peer in repaired.fields:
            if peer.index in targets or _NUMBER.fullmatch(peer.value) is None:
                continue
            peer_def = definition.field_at(peer.index)
            if peer_def is None or _numeric_role(peer_def.name) != role:
                continue
            format_matches += int(_numeric_signature(peer.value) == signature)
            value_matches += int(float(peer.value) == target_number)
    return format_matches - 2 * weird, value_matches, -weird


def _valid_geometry_split(
    repaired: IDFObject,
    vertex_count_index: int,
) -> bool:
    '''Require a geometry split to produce one legal polygon before ranking it.'''
    try:
        count = int(float(repaired.fields[vertex_count_index - 1].value))
        start = vertex_count_index
        points = tuple(
            tuple(
                float(repaired.fields[start + point * 3 + axis].value)
                for axis in range(3)
            )
            for point in range(count)
        )
    except (IndexError, ValueError):
        return False
    return validate_polygon(points)[0]


def _numeric_split_candidates(
    document: IDFDocument,
    idd: IDDSchema,
    diagnostics_text: str,
) -> list[SyntaxSite]:
    '''以 IDD 数值字段和同角色格式证据拆分被拼接的两个数值。'''
    diagnostics = diagnostics_text.casefold()
    sites = []
    for obj in document.objects:
        definition = idd.get(obj.object_type)
        if definition is None:
            continue
        vertex_count_index = next((
            field.index for field in definition.fields
            if "number of vertices" in field.name.casefold()
        ), None)
        geometry_short = False
        if (
            vertex_count_index is not None
            and vertex_count_index <= len(obj.fields)
        ):
            try:
                expected = vertex_count_index + 3 * int(
                    float(obj.fields[vertex_count_index - 1].value)
                )
                geometry_short = len(obj.fields) + 1 == expected
            except ValueError:
                geometry_short = False
        object_mentioned = bool(
            (obj.name and obj.name.casefold() in diagnostics)
            or obj.object_type.casefold() in diagnostics
        )
        candidates: list[tuple[tuple[int, int, int], int, int]] = []
        for field in obj.fields:
            current_def = definition.field_at(field.index)
            following_def = definition.field_at(field.index + 1)
            if (
                current_def is None
                or following_def is None
                or not current_def.token.upper().startswith("N")
                or not following_def.token.upper().startswith("N")
            ):
                continue
            malformed = _NUMBER.fullmatch(field.value) is None
            if not geometry_short and not (malformed and object_mentioned):
                continue
            for cut in range(1, len(field.value)):
                left = field.value[:cut]
                right = field.value[cut:]
                if _NUMBER.fullmatch(left) is None or _NUMBER.fullmatch(right) is None:
                    continue
                offset = field.start + cut
                proposed = parse_idf(_insert(document.text, offset, ","))
                if len(proposed.objects) != len(document.objects) or obj.index >= len(proposed.objects):
                    continue
                repaired = proposed.objects[obj.index]
                if len(repaired.fields) != len(obj.fields) + 1:
                    continue
                if definition.maximum_fields is not None and len(repaired.fields) > definition.maximum_fields:
                    continue
                if (
                    geometry_short
                    and vertex_count_index is not None
                    and not _valid_geometry_split(repaired, vertex_count_index)
                ):
                    continue
                candidates.append((
                    _split_score(repaired, definition, field.index),
                    offset,
                    field.index,
                ))
        if not candidates:
            continue
        candidates.sort(reverse=True)
        if len(candidates) > 1 and candidates[0][0] == candidates[1][0]:
            continue
        score, offset, field_index = candidates[0]
        if score[0] + score[1] <= 0:
            continue
        sites.append(SyntaxSite(
            kind="numeric_concatenation_comma",
            delimiter=",",
            offset=offset,
            line_number=document.text.count("\n", 0, offset) + 1,
            object_index=obj.index,
            object_type=obj.object_type,
            next_object_type=None,
            evidence=(
                "vertex_count_and_axis_format"
                if geometry_short else "idd_numeric_pair_and_role_format"
            ),
        ))
    return sites


def _missing_object_type_comma_sites(document: IDFDocument, idd: IDDSchema) -> list[SyntaxSite]:
    rows = _line_rows(document.text)
    sites: list[SyntaxSite] = []
    for line_index, (line_start, line) in enumerate(rows):
        code = _code(line)
        token = code.strip()
        if not token or token.endswith((",", ";")) or idd.get(token) is None:
            continue
        next_index = _next_significant(rows, line_index + 1)
        if next_index is None:
            continue
        leading = len(code) - len(code.lstrip())
        offset = line_start + leading + len(token)
        proposed = parse_idf(_insert(document.text, offset, ","))
        if len(proposed.objects) <= len(document.objects):
            continue
        sites.append(SyntaxSite(
            kind="missing_object_type_comma",
            delimiter=",",
            offset=offset,
            line_number=line_index + 1,
            object_index=None,
            object_type=token,
            next_object_type=None,
            evidence="unique_current_idd_object_type_line",
        ))
    return sites


def _missing_semicolon_sites(
    document: IDFDocument,
    idd: IDDSchema,
    diagnostics_text: str,
) -> list[SyntaxSite]:
    parsed_types = {
        match.group("object").strip().casefold()
        for match in _ERROR_PARSING.finditer(diagnostics_text)
    }
    if not parsed_types:
        return []
    rows = _line_rows(document.text)
    headers: list[tuple[int, str]] = []
    for index, (_, line) in enumerate(rows):
        # IDF field values commonly repeat an object type (for example a
        # Building named "Building").  The standard ``!- Field Name`` marker
        # proves that such a line is a field, not an adjacent object header.
        # Treating it as a header creates a false missing-semicolon site.
        if "!-" in line:
            continue
        token = _code(line).strip()
        if "," not in token:
            continue
        possible_type = token.split(",", 1)[0].strip()
        if idd.get(possible_type) is not None:
            headers.append((index, possible_type))
    sites: list[SyntaxSite] = []
    for position, (start, object_type) in enumerate(headers[:-1]):
        if object_type.casefold() not in parsed_types:
            continue
        next_header, next_type = headers[position + 1]
        if any(";" in _code(rows[index][1]) for index in range(start, next_header)):
            continue
        last = next((
            index for index in range(next_header - 1, start - 1, -1)
            if _code(rows[index][1]).strip()
        ), None)
        if last is None:
            continue
        line_start, line = rows[last]
        code = _code(line)
        offset = line_start + len(code)
        merged = _containing_object(document, offset)
        if merged is None or merged.object_type.casefold() != object_type.casefold():
            continue
        proposed = parse_idf(_insert(document.text, offset, ";"))
        if len(proposed.objects) != len(document.objects) + 1:
            continue
        if merged.index + 1 >= len(proposed.objects):
            continue
        if proposed.objects[merged.index].object_type.casefold() != object_type.casefold():
            continue
        if proposed.objects[merged.index + 1].object_type.casefold() != next_type.casefold():
            continue
        sites.append(SyntaxSite(
            kind="missing_semicolon",
            delimiter=";",
            offset=offset,
            line_number=last + 1,
            object_index=merged.index,
            object_type=object_type,
            next_object_type=next_type,
            evidence="err_object_and_adjacent_current_idd_headers",
        ))
    return sites


def detect_syntax_sites(
    document: IDFDocument,
    idd: IDDSchema,
    diagnostics_text: str,
    *,
    include_eof: bool = False,
) -> tuple[SyntaxSite, ...]:
    """Return deterministic sites only; callers must still require uniqueness."""

    sites = [
        *_blank_annotated_comma_sites(document, idd),
        *_missing_comma_sites(document, idd),
        *_missing_object_type_comma_sites(document, idd),
        *_numeric_split_candidates(document, idd, diagnostics_text),
        *_schedule_compact_sites(document, idd),
        *_missing_semicolon_sites(document, idd, diagnostics_text),
    ]
    if include_eof and "unterminated_object" in document.issues:
        offset = len(document.text.rstrip())
        sites.append(SyntaxSite(
            kind="unterminated_eof",
            delimiter=";",
            offset=offset,
            line_number=document.text.count("\n", 0, offset) + 1,
            object_index=None,
            object_type="",
            next_object_type=None,
            evidence="parser_eof_only_requires_user_confirmation",
        ))
    unique = {
        (row.kind, row.offset, row.delimiter, row.object_type): row
        for row in sites
    }
    return tuple(unique[key] for key in sorted(unique))


__all__ = ["SyntaxSite", "detect_syntax_sites"]
