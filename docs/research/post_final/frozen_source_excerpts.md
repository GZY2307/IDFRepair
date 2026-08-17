# Frozen V2 source excerpts

These excerpts are a review aid for the production method frozen under identity `3b9ad9447995f2b78313ca996a6a2ef2fa7711692054be184f470ea083f2928d`. Line numbers refer to the 2026-08-17 workspace snapshot. The excerpts are not an alternative implementation and were generated without changing production source.

## Canonical source provenance and complete compound transitions

Source: `src/idfrepair/semantic_graph_v2/ir.py:130-260`

```python
  130  @dataclass(frozen=True, slots=True)
  131  class FieldRef:
  132      """保存一个 IDF 字段的值、IDD 身份与精确 source span。"""
  133
  134      object_index: int
  135      object_type: str
  136      object_name: str
  137      field_index: int
  138      field_token: str
  139      field_name: str
  140      raw_value: str
  141      normalized_value: str
  142      start: int
  143      end: int
  144      extensible_ordinal: int | None = None
  145
  146      @property
  147      def field_id(self) -> str:
  148          """返回 snapshot-local 的稳定字段身份。"""
  149
  150          return f"object:{self.object_index}:field:{self.field_index}"
  151
  152
  153  @dataclass(frozen=True, slots=True)
  154  class ObjectRef:
  155      """保存一个 IDF object occurrence 及其有序字段。"""
  156
  157      object_id: str
  158      object_index: int
  159      raw_object_type: str
  160      normalized_object_type: str
  161      raw_name: str
  162      normalized_name: str
  163      start: int
  164      end: int
  165      fields: tuple[FieldRef, ...]
  166
  167      def field(self, index: int) -> FieldRef | None:
  168          """按 1-based index 返回字段，不对缺失 extensible 字段猜值。"""
  169
  170          if 1 <= index <= len(self.fields):
  171              return self.fields[index - 1]
  172          return None
  173
  174
  175  @dataclass(frozen=True, slots=True)
  176  class TypedIdentity:
  177      """记录一个 typed name lookup 的全部 candidate occurrences。"""
  178
  179      object_type: str
  180      object_name: str
  181      normalized_object_type: str
  182      normalized_object_name: str
  183      status: IdentityStatus
  184      object_ids: tuple[str, ...]
  185
  186
  187  @dataclass(frozen=True, slots=True)
  188  class PortRef:
  189      """记录由 explicit registry rule 证明的 typed HVAC port fact。"""
  190
  191      port_id: str
  192      object_id: str
  193      field_ref: FieldRef
  194      node_name: str
  195      normalized_node_name: str
  196      role: PortRole
  197      medium: FluidMedium
  198      applicability: PortApplicability
  199      port_group: str
  200      zone_side_role: ZoneSideRole
  201      rule_id: str
  202      rule_version: str
  203
  204
  205  @dataclass(frozen=True, slots=True)
  206  class FlowTransition:
  207      """记录一个 source-backed directed transition 或一对多/多对一 fact。"""
  208
  209      transition_id: str
  210      object_ref: ObjectRef
  211      inlet_ports: tuple[PortRef, ...]
  212      outlet_ports: tuple[PortRef, ...]
  213      medium: FluidMedium
  214      stream: FlowStreamRole
  215      circuit_id: str
  216      traversal_role: FlowTraversalRole
  217      rule_id: str
  218      rule_version: str
  219      applicability: ProjectionApplicability
  220
  221      def __post_init__(self) -> None:
  222          ports = (*self.inlet_ports, *self.outlet_ports)
  223          if not self.rule_id or not self.rule_version or not self.circuit_id:
  224              raise ValueError("flow_transition_identity")
  225          if not isinstance(self.stream, FlowStreamRole):
  226              raise ValueError("flow_transition_stream_role")
  227          if any(port.object_id != self.object_ref.object_id for port in ports):
  228              raise ValueError("flow_transition_cross_object_port")
  229          if any(port.medium is not self.medium for port in ports):
  230              raise ValueError("flow_transition_mixed_medium")
  231          if any(port.role is not PortRole.INLET for port in self.inlet_ports):
  232              raise ValueError("flow_transition_inlet_role")
  233          if any(port.role is not PortRole.OUTLET for port in self.outlet_ports):
  234              raise ValueError("flow_transition_outlet_role")
  235          if any(port.rule_version != self.rule_version for port in ports):
  236              raise ValueError("flow_transition_port_version_mismatch")
  237          port_ids = tuple(port.port_id for port in ports)
  238          if len(port_ids) != len(set(port_ids)):
  239              raise ValueError("flow_transition_duplicate_port")
  240          if (
  241              self.applicability is ProjectionApplicability.SUPPORTED_COMPLETE
  242              and (not self.inlet_ports or not self.outlet_ports)
  243          ):
  244              raise ValueError("complete_flow_transition_cardinality")
  245
  246      @property
  247      def complete(self) -> bool:
  248          """Derive transition completeness from status and exact evidence."""
  249
  250          nodes = tuple(
  251              port.normalized_node_name
  252              for port in (*self.inlet_ports, *self.outlet_ports)
  253          )
  254          return (
  255              self.applicability is ProjectionApplicability.SUPPORTED_COMPLETE
  256              and bool(self.inlet_ports)
  257              and bool(self.outlet_ports)
  258              and all(nodes)
  259              and len(nodes) == len(set(nodes))
  260          )
```

## Constraint admission model

Source: `src/idfrepair/semantic_graph_v2/registry.py:42-69`

```python
   42  @dataclass(frozen=True, slots=True)
   43  class ConstraintSpec:
   44      """一个不含 benchmark selector 的 immutable constraint declaration。"""
   45
   46      constraint_id: str
   47      relation_class: RelationClass
   48      evidence_class: EvidenceClass
   49      admission_status: AdmissionStatus
   50      scope_type: str
   51      evaluator_key: str
   52      candidate_generator_key: str
   53      semantic_equivalence_key: str
   54      latent_factor_kind: str
   55      evidence_note: str
   56
   57      @property
   58      def hard(self) -> bool:
   59          return self.admission_status is AdmissionStatus.ADMIT_SAFE_AUTO
   60
   61
   62  @dataclass(frozen=True, slots=True)
   63  class ConstraintRegistry:
   64      specs: tuple[ConstraintSpec, ...]
   65
   66      def __post_init__(self) -> None:
   67          identifiers = tuple(spec.constraint_id for spec in self.specs)
   68          if len(identifiers) != len(set(identifiers)):
   69              raise ValueError("duplicate_constraint_id")
```

## Target-free whole-model scanner boundary

Source: `src/idfrepair/semantic_graph_v2/scan.py:1624-1676`

```python
 1624  def scan_ir(
 1625      model: ModelIR,
 1626      *,
 1627      registry: ConstraintRegistry | None = None,
 1628  ) -> ScanResult:
 1629      """对一个 canonical snapshot 执行全部 active constraints。"""
 1630
 1631      active = registry or production_registry()
 1632      violations: list[Violation] = []
 1633      applicability: list[ApplicabilityRecord] = []
 1634      for spec in active.specs:
 1635          evaluator = _EVALUATORS.get(spec.evaluator_key)
 1636          if evaluator is None:
 1637              applicability.append(ApplicabilityRecord(
 1638                  constraint_id=spec.constraint_id,
 1639                  scope_id="model",
 1640                  applied=False,
 1641                  reason="evaluator_not_registered",
 1642              ))
 1643              continue
 1644          applied, reason = _constraint_applicability(model, spec)
 1645          if not applied:
 1646              applicability.append(ApplicabilityRecord(
 1647                  constraint_id=spec.constraint_id,
 1648                  scope_id="model",
 1649                  applied=False,
 1650                  reason=reason,
 1651              ))
 1652              continue
 1653          produced = evaluator(model, spec)
 1654          violations.extend(produced)
 1655          applicability.append(ApplicabilityRecord(
 1656              constraint_id=spec.constraint_id,
 1657              scope_id="model",
 1658              applied=True,
 1659              reason=reason,
 1660          ))
 1661      return ScanResult(
 1662          model=model,
 1663          violations=tuple(sorted(violations, key=lambda row: row.violation_id)),
 1664          applicability=tuple(applicability),
 1665      )
 1666
 1667
 1668  def scan_model(
 1669      document: IDFDocument,
 1670      idd: IDDSchema,
 1671      *,
 1672      registry: ConstraintRegistry | None = None,
 1673  ) -> ScanResult:
 1674      """Public target-free boundary：只接收 faulty/current IDF 与 exact IDD。"""
 1675
 1676      return scan_ir(build_model_ir(document, idd), registry=registry)
```

## Candidate-domain completeness states

Source: `src/idfrepair/semantic_graph_v2/candidates.py:46-78`

```python
   46  class CandidateDomainStatus(_StringEnum):
   47      COMPLETE = "COMPLETE"
   48      INCOMPLETE_UNSUPPORTED = "INCOMPLETE_UNSUPPORTED"
   49      TRUNCATED = "TRUNCATED"
   50
   51
   52  @dataclass(frozen=True, slots=True)
   53  class CandidateSet:
   54      violation_id: str
   55      constraint_id: str
   56      status: CandidateDomainStatus
   57      candidates: tuple[SemanticEdit, ...]
   58      reason: str
   59
   60
   61  @dataclass(frozen=True, slots=True)
   62  class CandidateGeneration:
   63      model_sha256: str
   64      candidate_sets: tuple[CandidateSet, ...]
   65
   66      def for_violation(self, violation_id: str) -> CandidateSet | None:
   67          return next(
   68              (row for row in self.candidate_sets if row.violation_id == violation_id),
   69              None,
   70          )
   71
   72      @property
   73      def all_edits(self) -> tuple[SemanticEdit, ...]:
   74          unique: dict[str, SemanticEdit] = {}
   75          for domain in self.candidate_sets:
   76              for edit in domain.candidates:
   77                  unique.setdefault(edit.semantic_signature, edit)
   78          return tuple(unique[key] for key in sorted(unique))
```

## Materialized field/relation preconditions and atomic write-back

Source: `src/idfrepair/semantic_graph_v2/edits.py:173-225`

```python
  173  def _validate_preconditions(document, edits: tuple[SemanticEdit, ...]) -> None:  # type: ignore[no-untyped-def]
  174      selected_fields: dict[tuple[int, int], FieldValuePrecondition] = {}
  175      for edit in edits:
  176          for precondition in edit.field_preconditions:
  177              key = (precondition.object_index, precondition.field_index)
  178              prior = selected_fields.get(key)
  179              if prior is not None and prior != precondition:
  180                  raise SemanticEditConflict(
  181                      f"conflicting_field_precondition:{precondition.field_id}"
  182                  )
  183              selected_fields[key] = precondition
  184
  185      for (object_index, field_index), precondition in selected_fields.items():
  186          if not 0 <= object_index < len(document.objects):
  187              raise SemanticEditConflict("field_precondition_object_out_of_range")
  188          obj = document.objects[object_index]
  189          if canonical(obj.object_type) != canonical(precondition.object_type):
  190              raise SemanticEditConflict("field_precondition_object_type_mismatch")
  191          if canonical(obj.name) != canonical(precondition.object_name):
  192              raise SemanticEditConflict("field_precondition_object_name_mismatch")
  193          if not 1 <= field_index <= len(obj.fields):
  194              raise SemanticEditConflict("field_precondition_index_out_of_range")
  195          if obj.fields[field_index - 1].value != precondition.expected_value:
  196              raise SemanticEditConflict(
  197                  f"field_precondition_value_mismatch:{precondition.field_id}"
  198              )
  199
  200      for edit in edits:
  201          for precondition in edit.relation_preconditions:
  202              if document.sha256 != precondition.expected_document_sha256:
  203                  raise SemanticEditConflict(
  204                      "relation_precondition_snapshot_mismatch:"
  205                      f"{precondition.variable_id}"
  206                  )
  207
  208
  209  def apply_semantic_edits(text: str, edits: tuple[SemanticEdit, ...]) -> str:
  210      """在原 snapshot 上原子应用 edits，保留所有未触及 bytes。"""
  211
  212      document = parse_idf(text)
  213      _validate_preconditions(document, edits)
  214      selected: dict[tuple[int, int], FieldEdit] = {}
  215      for edit in edits:
  216          for field_edit in edit.field_edits:
  217              key = (field_edit.object_index, field_edit.field_index)
  218              prior = selected.get(key)
  219              if prior is not None:
  220                  if (
  221                      prior.new_value != field_edit.new_value
  222                      or prior.old_value != field_edit.old_value
  223                  ):
  224                      raise SemanticEditConflict(
  225                          f"conflicting_field_write:{field_edit.field_id}"
```

## Bounded complete objective levels and unique-optimum decision

Source: `src/idfrepair/semantic_graph_v2/solver.py:254-397`

```python
  254  def _solve_component(
  255      text: str,
  256      idd: IDDSchema,
  257      initial_scan: ScanResult,
  258      component: ConflictComponent,
  259      *,
  260      registry: ConstraintRegistry | None,
  261      limits: SolverLimits,
  262  ) -> ComponentDecision:
  263      if len(component.violations) > limits.max_component_violations:
  264          return _decision(
  265              component,
  266              ComponentDecisionStatus.SEARCH_EXHAUSTED,
  267              search_exhausted=True,
  268              reasons=("max_component_violations_exceeded",),
  269          )
  270      if any(
  271          domain.status is CandidateDomainStatus.TRUNCATED
  272          for domain in component.candidate_sets
  273      ):
  274          return _decision(
  275              component,
  276              ComponentDecisionStatus.SEARCH_EXHAUSTED,
  277              search_exhausted=True,
  278              reasons=("candidate_domain_truncated",),
  279          )
  280      if any(
  281          domain.status is CandidateDomainStatus.INCOMPLETE_UNSUPPORTED
  282          for domain in component.candidate_sets
  283      ):
  284          return _decision(
  285              component,
  286              ComponentDecisionStatus.UNSUPPORTED,
  287              candidate_domain_complete=False,
  288              reasons=tuple(sorted({
  289                  domain.reason for domain in component.candidate_sets
  290                  if domain.status is CandidateDomainStatus.INCOMPLETE_UNSUPPORTED
  291              })),
  292          )
  293
  294      edits = component.candidate_edits
  295      if len(edits) > limits.max_candidate_edits:
  296          return _decision(
  297              component,
  298              ComponentDecisionStatus.SEARCH_EXHAUSTED,
  299              search_exhausted=True,
  300              reasons=("max_candidate_edits_exceeded",),
  301          )
  302      if not edits:
  303          return _decision(
  304              component,
  305              ComponentDecisionStatus.NEEDS_INPUT,
  306              candidate_domain_complete=True,
  307              reasons=("complete_domain_has_no_candidate",),
  308          )
  309
  310      initial_ids = {row.violation_id for row in initial_scan.hard_violations}
  311      component_ids = {row.violation_id for row in component.violations}
  312      outside_ids = initial_ids - component_ids
  313      evaluated = 0
  314      valid: list[tuple[tuple[SemanticEdit, ...], int]] = []
  315      exhausted = False
  316      upper = min(len(edits), limits.max_semantic_edits)
  317      for semantic_count in range(1, upper + 1):
  318          # Uniqueness requires the whole objective level.  If the remaining
  319          # budget cannot enumerate that level, fail before sampling a prefix;
  320          # a prefix could find S1 while silently missing an equal optimum S2.
  321          if evaluated + comb(len(edits), semantic_count) > limits.max_evaluated_sets:
  322              exhausted = True
  323              break
  324          level_valid: list[tuple[tuple[SemanticEdit, ...], int]] = []
  325          for indexes in combinations(range(len(edits)), semantic_count):
  326              if evaluated >= limits.max_evaluated_sets:
  327                  exhausted = True
  328                  break
  329              evaluated += 1
  330              selected = tuple(edits[index] for index in indexes)
  331              try:
  332                  repaired = apply_semantic_edits(text, selected)
  333              except SemanticEditConflict:
  334                  continue
  335              post = scan_model(parse_idf(repaired), idd, registry=registry)
  336              post_ids = {row.violation_id for row in post.hard_violations}
  337              if post_ids != outside_ids:
  338                  continue
  339              level_valid.append((selected, _field_cost(selected)))
  340          if exhausted:
  341              break
  342          if level_valid:
  343              minimum_fields = min(cost for _, cost in level_valid)
  344              valid = [row for row in level_valid if row[1] == minimum_fields]
  345              break
  346
  347      if exhausted:
  348          return _decision(
  349              component,
  350              ComponentDecisionStatus.SEARCH_EXHAUSTED,
  351              evaluated_sets=evaluated,
  352              candidate_domain_complete=True,
  353              search_exhausted=True,
  354              reasons=("max_evaluated_sets_exceeded",),
  355          )
  356      if not valid:
  357          reason = (
  358              "max_semantic_edits_insufficient"
  359              if len(edits) > limits.max_semantic_edits
  360              else "no_globally_closing_edit_set"
  361          )
  362          return _decision(
  363              component,
  364              ComponentDecisionStatus.NEEDS_INPUT,
  365              evaluated_sets=evaluated,
  366              candidate_domain_complete=True,
  367              reasons=(reason,),
  368          )
  369
  370      equivalent: dict[tuple[str, ...], tuple[SemanticEdit, ...]] = {}
  371      for selected, _ in valid:
  372          equivalent.setdefault(_semantic_signature(selected), selected)
  373      signatures = tuple(sorted(equivalent))
  374      objective = (len(valid[0][0]), valid[0][1])
  375      if len(signatures) != 1:
  376          return _decision(
  377              component,
  378              ComponentDecisionStatus.AMBIGUOUS,
  379              alternative_count=len(signatures),
  380              objective=objective,
  381              evaluated_sets=evaluated,
  382              candidate_domain_complete=True,
  383              reasons=("multiple_equal_optimum_semantic_edit_sets",),
  384              alternative_signatures=signatures,
  385          )
  386      selected = equivalent[signatures[0]]
  387      return _decision(
  388          component,
  389          ComponentDecisionStatus.UNIQUE_REPAIR,
  390          selected_edits=selected,
  391          alternative_count=1,
  392          objective=objective,
  393          evaluated_sets=evaluated,
  394          candidate_domain_complete=True,
  395          reasons=("unique_complete_minimum",),
  396          alternative_signatures=signatures,
  397      )
```

## Current-IDF + exact-IDD runtime and global closure

Source: `src/idfrepair/semantic_graph_v2/runtime.py:124-278`

```python
  124  def repair_model(
  125      text: str,
  126      idd: IDDSchema,
  127      *,
  128      registry: ConstraintRegistry | None = None,
  129      limits: SolverLimits = SolverLimits(),
  130  ) -> RepairOutcome:
  131      """只用 current IDF + exact IDD 执行 scan、joint solve 与 global closure。"""
  132
  133      timings: dict[str, float] = {}
  134      started = perf_counter()
  135      document = parse_idf(text)
  136      timings["parse"] = perf_counter() - started
  137      started = perf_counter()
  138      model = build_model_ir(document, idd)
  139      timings["ir_build"] = perf_counter() - started
  140      started = perf_counter()
  141      initial = scan_ir(model, registry=registry)
  142      timings["constraint_scan"] = perf_counter() - started
  143      if document.issues:
  144          unresolved = tuple(row.violation_id for row in initial.hard_violations)
  145          return RepairOutcome(
  146              status=RepairStatus.PROCESS_FAILURE,
  147              input_text=text,
  148              output_text=text,
  149              initial_scan=initial,
  150              final_scan=initial,
  151              candidate_generation=None,
  152              components=(),
  153              decisions=(),
  154              selected_edits=(),
  155              unresolved_violation_ids=unresolved,
  156              reason="|".join(document.issues),
  157              phase_timings=_phase_timings(timings),
  158          )
  159      if not initial.hard_violations:
  160          return RepairOutcome(
  161              status=RepairStatus.VALID,
  162              input_text=text,
  163              output_text=text,
  164              initial_scan=initial,
  165              final_scan=initial,
  166              candidate_generation=None,
  167              components=(),
  168              decisions=(),
  169              selected_edits=(),
  170              unresolved_violation_ids=(),
  171              reason="no_active_hard_violations",
  172              phase_timings=_phase_timings(timings),
  173          )
  174
  175      started = perf_counter()
  176      candidates = generate_candidates(initial.model, initial)
  177      timings["candidate_generation"] = perf_counter() - started
  178      started = perf_counter()
  179      components = build_conflict_components(initial.hard_violations, candidates)
  180      timings["conflict_graph"] = perf_counter() - started
  181      started = perf_counter()
  182      decisions = solve_components(
  183          text,
  184          idd,
  185          initial,
  186          components,
  187          registry=registry,
  188          limits=limits,
  189      )
  190      timings["solver"] = perf_counter() - started
  191      selected = _unique_edits(decisions)
  192      if not selected:
  193          status = _status_without_repairs(decisions)
  194          unresolved = tuple(row.violation_id for row in initial.hard_violations)
  195          return RepairOutcome(
  196              status=status,
  197              input_text=text,
  198              output_text=text,
  199              initial_scan=initial,
  200              final_scan=initial,
  201              candidate_generation=candidates,
  202              components=components,
  203              decisions=decisions,
  204              selected_edits=(),
  205              unresolved_violation_ids=unresolved,
  206              reason="no_component_has_a_unique_complete_minimum",
  207              phase_timings=_phase_timings(timings),
  208          )
  209
  210      started = perf_counter()
  211      try:
  212          output = apply_semantic_edits(text, selected)
  213      except SemanticEditConflict as exc:
  214          timings["global_closure"] = perf_counter() - started
  215          unresolved = tuple(row.violation_id for row in initial.hard_violations)
  216          return RepairOutcome(
  217              status=RepairStatus.PROCESS_FAILURE,
  218              input_text=text,
  219              output_text=text,
  220              initial_scan=initial,
  221              final_scan=initial,
  222              candidate_generation=candidates,
  223              components=components,
  224              decisions=decisions,
  225              selected_edits=(),
  226              unresolved_violation_ids=unresolved,
  227              reason=f"combined_edit_conflict:{exc}",
  228              phase_timings=_phase_timings(timings),
  229          )
  230
  231      final = scan_model(parse_idf(output), idd, registry=registry)
  232      timings["global_closure"] = perf_counter() - started
  233      final_ids = {row.violation_id for row in final.hard_violations}
  234      initial_ids = {row.violation_id for row in initial.hard_violations}
  235      expected_unresolved = _unresolved_component_ids(components, decisions)
  236      if final_ids != expected_unresolved or not final_ids.issubset(initial_ids):
  237          unresolved = tuple(row.violation_id for row in initial.hard_violations)
  238          return RepairOutcome(
  239              status=RepairStatus.NEEDS_INPUT,
  240              input_text=text,
  241              output_text=text,
  242              initial_scan=initial,
  243              final_scan=initial,
  244              candidate_generation=candidates,
  245              components=components,
  246              decisions=decisions,
  247              selected_edits=(),
  248              unresolved_violation_ids=unresolved,
  249              reason="combined_global_closure_rejected",
  250              phase_timings=_phase_timings(timings),
  251          )
  252
  253      unresolved = tuple(sorted(final_ids))
  254      if not unresolved:
  255          status = RepairStatus.REPAIRED_COMPLETE
  256          reason = "all_active_hard_violations_closed"
  257      elif any(
  258          decision.status is ComponentDecisionStatus.UNSUPPORTED
  259          for decision in decisions
  260      ):
  261          status = RepairStatus.PARTIAL_UNSUPPORTED
  262          reason = "unique_components_committed_with_unsupported_residual"
  263      else:
  264          status = RepairStatus.PARTIAL_NEEDS_INPUT
  265          reason = "unique_components_committed_with_unchanged_residual"
  266      return RepairOutcome(
  267          status=status,
  268          input_text=text,
  269          output_text=output,
  270          initial_scan=initial,
  271          final_scan=final,
  272          candidate_generation=candidates,
  273          components=components,
  274          decisions=decisions,
  275          selected_edits=selected,
  276          unresolved_violation_ids=unresolved,
  277          reason=reason,
  278          phase_timings=_phase_timings(timings),
```


