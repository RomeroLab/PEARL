"""Five-role experiment loop restricted to declared setup and camera evidence."""
import json
import uuid
from copy import deepcopy
from pearl.brain.analysis_utilities import execute_utility, utility_schemas
from pearl.runtime.contracts import Actor, ProceedSignal
from pearl.runtime.contracts import ActionSpec
from pearl.runtime.acquisition_context import acquisition_context
from pearl.runtime.requirement_provenance import CLAIM_GROUNDING, OPERATIONAL_ASSUMPTIONS
from pearl.runtime.evidence_history import evidence_history_view
from pearl.runtime.requirement_scopes import replication_requirement_scope
from pearl.runtime.acquisition_schedule import acquisition_schedule, validate_locations
from pearl.runtime.action_inventory import preparation_focus, validate_volumes
from pearl.runtime.analysis import explain_initial_window
from pearl.runtime.analysis_advice import publish_proposals, validate_proposals
from pearl.runtime.analysis_advice import respond as respond_analysis_advice
from pearl.runtime.analysis_basis import adoption_intervals, basis_choices, basis_schema, public_copy, validate_basis
from pearl.runtime.analysis_memory import analysis_memory, record_decision, require_eligible, validate_adoption
from pearl.runtime.blackboard import Blackboard
from pearl.runtime.analysis_support import SupportingInputError
from pearl.runtime.capacity import plate_transfer_accounting
from pearl.runtime.cohort_memory import adoption_coverage, cohort_memory, validate_cohort_adoption, validate_updates
from pearl.runtime.comparison_timing import endpoint_timing_audit, endpoint_timing_schema, timing_context, timing_schema, validate_timing
from pearl.runtime.context_view import ContextSectionUnavailable, DETAIL_SECTIONS, archive_receipt, project_context, reference_context_collections, read_context_details, read_shared_events, shared_message_context
from pearl.runtime.decision_record import DecisionValidationError, aggregate_advice, assessment_schema, current_decision, decision_schema, decision_update_schema, design_review_target, prepare_decision, publish_decision, report_review_target, validate_assessment
from pearl.runtime.experiment_practice import EXPERIMENT_PRACTICE, operation_state
from pearl.runtime.rejected_decision import REJECTION_TYPE, rejected_memory, validation_cause
from pearl.runtime.measured_color import compare_measured_color, measured_color_range, resolve_color_target, simulate_measured_mix
from pearl.runtime.measured_endpoint_series import measured_endpoint_series
from pearl.runtime.measured_kinetics import course_selection_diagnostics, measured_initial_rate, measured_mm, select_rate_course
from pearl.runtime.notebook import action_history, nominal_transfer_balance, preparation_summary
from pearl.runtime.observation_query import find_observations
from pearl.runtime.observation_references import ACQUIRED_IDS_DESCRIPTION, acquired_reference_diagnostics, bind_references, resolve_references
from pearl.runtime.review_memory import ReviewConcernSelectionError, resolve_concern, review_memory
from pearl.runtime.task_resolution import GUIDANCE, read_resolution, resolution_schema
from pearl.brain.tool_schema import strict_function_tool
from pearl.runtime.transport import TABLE_GUIDE, compact_context, order_context
from pearl.state.events import AnomalyMatchEvent, KnowledgeRequestEvent, KnowledgeResponseEvent, ObservationEvent, PeerReviewDispositionEvent, PlanEvent, PredictionEvent, ToolCallEvent, WorkingPlanDeclaredEvent

class PendingReviewError(ValueError):
    """Identify the current queue without disposing advice or authorizing work."""

    def __init__(self, message, pending, events):
        super().__init__(message)
        authors = {event.event_id: event.source_agent for event in events}
        self.feedback = {'response_tool': 'respond_to_review', 'pending_reviews': [{'review_id': review['event_id'], 'source_agent': authors.get(review['event_id'], review.get('source_agent'))} for review in pending]}
REASONER = "Develop and carry out a method for the public goal using available tools.\nTest conditional predictive models separately from identifying a cause; a missing procedure alone does not imply incapability. Ground discrepancies in acquired evidence. Consider handling,\ntiming, quantization and uncertainty. Stock labels and priors are not observations.\nPredictor and Watchdog advice requires a reasoned response before another liquid action. You may\nreject advice with grounds; canonical report claims permit logical rejection with [] and no pending action.\nPhysical proceed/reject requires observations and safeguards. Only proceed authorizes the pending action; accept/revise/reject\nwithdraw it. Safety limits cannot be overridden. transfer/mix submits an action for Predictor review before Actor execution.\nacknowledge preserves the concern and queued action without execution. Use manage_pending_action\nto proceed or withdraw by exact action ID after handling reviews; do not resubmit held actions.\nrecord_plan stores notes only; it neither submits nor starts review.\nUse record_decision with decision_ref and small updates; omitted fields and plan/timing/cohorts\nstay unchanged. Refresh basis, working_model and next_step consistently before final reference reuse.\nrecord_plan.cohort_updates preserves member identity, location, rationale and evidence across plans.\nKeep preparation_id null during assembly despite premix images; bind only the observed completed\nintended stage's location@last_change_event_id. Reviewed liquid work needs no binding. After material\nchange, dispose the old identity and create a new member; never rebind it. Explain nonadoption from\ncalculations or reported color stages, distinguishing diagnostics, whole-range decisions and omitted\nreplicates. Enrollment, disposition and timing matches do not prove scientific validity.\nDeclare acquisition_locations for chosen common-age acquisition. acquisition_schedule reports capture\noverhead, future/historical windows and missing preparations; it authorizes nothing. Before replacement,\nassess acquired evidence, existing candidates and unresolved obligations.\nscientific_review_memory preserves accepted/revised/acknowledged concerns. Proceed allows one action,\nnot resolution. resolve_review_concern needs grounds/acquired IDs (canonical report logic permits []),\nnever executes. find_acquired_observations searches history by chosen times/locations; assess applicability.\nRecord preparation sequence and assessment stage before multi-operation work. Each transfer/mix\nproposes one operation. If advice confuses an intermediate step with the endpoint, clarify the plan\nand explicitly proceed with grounds; repeated resubmission adds no evidence.\nUse respond_to_review only for pending_reviews. Acquisition, Knowledge, calculation, revision or\njustified finishing remain available. record_plan retains intent/comparisons/questions.\ncommanded_preparations gives nominal stock-equivalent contents; read_action_history gives commands/times,\nnot verified delivery/identity. read_measurements and working_plan_acquisition_context bind readings to\npreparation and elapsed times at capture, not current contents/clock.\nAssess historical/current comparability. analysis_memory preserves calculations/exclusions.\nPeer analysis proposals persist in analysis_memory.peer_advice independently of action approval.\nBefore using affected observations, respond_to_analysis_advice accepts the proposed exclusion or\nrejects it with acquired evidence and rationale. Unrelated work remains available; an action's\nsupported verdict does not resolve an analysis condition. Do not invent exclusions for debate.\nscientific_review_validation_error is unvalidated advice, not accepted evidence/exclusion. Respond\nwith evidence/rationale to a pending invalid report review before finish. Acceptance cannot apply\nmalformed exclusions; revise analysis or record valid decisions, or reject the premise with grounds.\nIn finish, enzyme reports adopt acquired calculation_ids; color reports may use adopted_measurement_ids\nfor final material stages. measurement_ids are citations, not adoption, and may include diagnostics.\nPending color members need adoption or reasoned nonadopt; preserve evidence. analyze_measured_endpoint_series\nfits acquired IDs under public nominal conditions; analysis_memory preserves results. Justify comparison,\ntiming and controls: fit quality proves neither comparability nor independence. Tools use supplied inputs.\nFinish records a claim, not success. Make one tool call per turn. Configured Predictor review\nassesses ending the original task. Concerns permit revision or a justified stop, not repeated report-review\nloops or liquid execution. Self-chosen trial counts do not establish infeasibility.\nAll five roles can access the shared camera observations."
PREDICTOR = "Review goal progress using public setup, camera and command evidence.\nSeparate conditional prediction from causal identification; check falsifiable assumptions and\nequipment/timing limits. Offer testable refinements when justified. Invent no observations or faults.\nConsult Knowledge or calculate from supplied data when useful. Submit a supported, concern, or uncertain review\nwith rationale and optionally numeric expected camera intervals. Each expectation identifies a\nlocation and field (od_estimate, captured_at_s, or rgb_0/rgb_1/rgb_2), lower and upper bounds.\nBounds must come from public evidence or a stated hypothesis. proposed_action is one operation.\nReview an intermediate operation against the whole plan, model implications and contrary evidence;\nit need not already yield the final target. Do not infer undocumented later operations or excuse a\nwhole-plan mismatch as an unfinished step. Camera expectations describe the immediate post-operation state, not an\nunexecuted final mixture. Distinguish incomplete and failed completed preparations.\nIf the sequence is unclear, identify the missing information rather than requiring a single-operation\ntool to encode an entire sequence. Do not demand debate for its own sake.\nUse analysis_memory to reconcile selected calculations with standing exclusions and earlier results.\nUse cohort_memory and acquisition_schedule when present to check enrollment, preparation identities,\nnonadoption rationale, future capture feasibility and already acquired evidence. An expired future\nwindow does not erase historical matches. Neither matching timing nor structural cohort coverage\nproves comparability, independent replication or a scientifically valid exclusion.\nA restricted-window failure describes only that window. At report review, check adopted calculation_ids\nand whether the conclusion reconciles any changed scientific interpretation. Exclusions are Reasoner's\nexplicit decisions; advise on their basis without silently changing them. For kinetic reviews,\nput material exclusion advice about acquired observations in analysis_exclusions with exact acquired\nIDs, their target location and its scientific basis, even if the proposed action is supported.\nUse a separate proposal for each target location; cross-location evidence citations are allowed. Use an empty list when no\nsuch advice applies. General cautions or future observations are not acquired-data exclusions.\nDo not leave an acquired-data exclusion solely in rationale prose. Reopen disposed advice only for material new grounds: observations, corrected reasoning or changed\napplicability; explain their consequence. Reasoner may reject ungrounded objections.\nScientific concerns are advisory; Reasoner may respond with evidence. Make one tool call per turn."
FEASIBILITY = ' Separate original goal/method and stopping/report accuracy. Assess if prior model relation/domain entails goal before trials. Use declarations/priors as conditional premises. Match model/evidence precision to the claim: quantitative gaps need not defeat qualitative consequences; qualitative priors alone give no numeric bounds. Assess applicability/contrary evidence; hypothetical exceptions are not counterevidence. Supported requirement conflicts permit clarification without universal proof or physical trial. For recovery/stopping, reconcile earlier decision-changing alternatives and what changed; trial count/possibility alone decide neither. Uncertainty permits tests. Safety binds.'
KNOWLEDGE_PRACTICE = ' Consult Knowledge on disputed science. Check source_kind/applicability/limitations; cite knowledge_id and justify adoption/rejection. Retrieval is optional, not acquired evidence. Watchdog prediction_feedback informs forecasts, not fault diagnosis or pending-review obligations.'
REASONER += KNOWLEDGE_PRACTICE
PREDICTOR += KNOWLEDGE_PRACTICE
COVERAGE_GUIDANCE = ' Calculations cover chosen inputs/intervals. analysis_memory.observation_coverage logs later data/preparation, not eligibility/fit-extension advice. Use read_measurements/read_action_history to assess precision, interval extent, capture resolution and preparation changes. Justify retention/reanalysis/acquisition; Do not select favorable replicates or omit applicable data to meet agreement. Preserve conflicts/inconclusive results.'
REASONER += COVERAGE_GUIDANCE
PREDICTOR += COVERAGE_GUIDANCE
CONDITION_GUIDANCE = ' Check analysis_memory calculation_id nominal_conditions/stock_references: nominal at calculation, not measured/current. Aggregate\nbound_rates preserve individual conditions. Similar rates prove neither matched conditions nor independence. Explain applicability/differences; missing metadata is unknown.'
COMPARISON_TIMING = ' For a chosen common-age comparison, record comparison_timing reference, target age and\njustified tolerance; unknown fields may be null. Resolve relevant unknowns before expansion; diagnostics\nremain possible. A timing promise is not a schedule. Check handling/readout overhead, signal resolution\nand existing evidence before replacement. Timing arithmetic covers explicitly cited observations,\nnot all camera readings or automatic adoption. Endpoint comparison_timing_audit covers selected samples\nand controls explicitly in scope. Choose optional comparison_timing.measurement_ids or null for another\nmethod; when omitted, only selected IDs cited by the active plan inherit its premise. Explain differently\ntimed controls in comparison_rationale. Exploratory mismatches are allowed; final adoption requires\nresolving and matching the chosen premise. A new method requires a new calculation; notes cannot rewrite results.\nNull/omitted plan comparison_timing clears future scope. Neither common age nor a mixing reference\nis mandatory. Predictor assesses premises without automatically excluding intermediate observations\nor treating timing agreement as scientific validity.'
REASONER += COMPARISON_TIMING
PREDICTOR += COMPARISON_TIMING
CAPTURE_FORECAST = " For captured_at_s forecasts include the proposed operation's declared duration and\ncamera acquisition duration. Distinguish these assumed durations from measured completion times.\nUse justified uncertainty bounds; expected readout overhead is not an observation discrepancy."
PREDICTOR += CAPTURE_FORECAST
REASONER += FEASIBILITY
PREDICTOR += FEASIBILITY
PREDICTOR += " When proposed_report is present, assess that conclusion and stopping rationale\nagainst the public goal, acquired evidence and available constraints, not a future liquid action.\nDistinguish an incompatible objective or safety/physical limit from failure of a tested formulation.\nPreserve the claim's assumptions and scope; identify a concrete defect before demanding more tests.\nNeither a trial count nor residual possibility decides feasibility. Never demand unsafe continuation.\nSubmit no future camera expectations for report review. Reasoner retains the final scientific decision."
REASONER += GUIDANCE
PREDICTOR += GUIDANCE
PREDICTOR += ' proposed_decision requests a scientific judgment before operational review.\nCompare its purpose, scope and alternatives with the public goal, evidence and constraints.\nPhysical feasibility alone does not establish scientific necessity. Supply decision_assessment,\nempty expected_volumes and no future expectations. Identify concrete grounds for concern or\nuncertainty; no recovery or stopping choice is prescribed. Reasoner may respond with grounds.\nA revised decision is reviewed anew; every operation requires separate review. Neither\nscientific support nor its disposition authorizes an unreviewed operation.'
REASONER += OPERATIONAL_ASSUMPTIONS
PREDICTOR += OPERATIONAL_ASSUMPTIONS
EMPIRICAL_PRACTICE = ' Failed diagnostics may inform a local input-response model, not its mechanism.\nJustify domain, uncertainty and support; conditional response claims need not prove mechanism.\nFit alone cannot prove global validity or repeatability. Compare color_comparison_memory inputs/responses; page omitted rows.\nState supporting/contrary evidence, competing explanations, changed variables and recorded conditions.\nPredictor may forecast immediate camera intervals when justified; unknown bounds remain unknown.\nTiming agreement does not validate a model; Watchdog residuals challenge forecasts, not establish causes.\nWeigh decision information against consequences and resource cost. A diagnostic may be inconclusive;\nthat is not positive evidence. Correct overstated inference before increasing intervention.\nDeclare decision_basis.experiment: question, completion_conditions, comparison_conditions,\nearly_stop_conditions. Compare preparation stage, loading, timing and history before alleging anomaly;\nan intermediate is not an endpoint failure. Pause and reassess when a stopping safeguard triggers.\nChanging/withdrawing conditions needs experiment_change with stage, comparison, challenged premise,\nimpact, evidence, rationale and recovery/reuse scope. Predictor checks previous_experiment;\nuncertainty alone does not establish invalidity. retain_experiment_from explicitly preserves exact\nconditions during a decision revision; it does not establish completion. Retain applicable data,\njustify exclusions and assess the remaining evidence. One failed method does not exhaust the goal.\nDo not repeat uninformative actions or infer safety from ignorance. Revise, clarify or stop with grounds\nwhen no informative acceptable test is supported. External constraints and safety remain binding.'
REASONER += EMPIRICAL_PRACTICE
PREDICTOR += EMPIRICAL_PRACTICE
OBSERVATION_CITATIONS = ' Plan/review observation_references bind facts to exact acquired IDs/locations. Check values/times; distinguish setup, priors and hypotheses. Use [] without observations; invent no evidence/anomalies. Literal acquired IDs in text also bind; wrong explicit locations fail. Binding proves provenance, not adoption/verdict. read_retrieval_receipt reads exact older results.'
REASONER += OBSERVATION_CITATIONS
PREDICTOR += OBSERVATION_CITATIONS
ANALYSIS_BASIS = " At kinetic adoption, analysis_basis must cover every adopted rate, including fit ancestors. Group by rationale and after_preparation_change/after_preparation_mix/explicit_interval; basis is no validity certificate. Check selection_diagnostics: bounds/fitted prefix/neighbors differ; flags prove neither exclusion nor validity. Correct prior numeric errors (prose fixes need no new data). Preserve course interval_basis; new basis/inputs require recalculation. Examine acquired records before new acquisition. Compare intervals with acknowledged timing/standing plan; revised premises need acquired grounds, not fit agreement. explicit_interval permits reasoned alternatives, not verified homogeneity; exploration stays available.\nsupporting_basis covers each group's exact correction inputs by basis/rationale. Assess preparation history/matrix/values/applicability: reaction timing does not validate controls. Reconcile prior control/reaction premises; fit alone is insufficient. supporting_observations retains old records. Calibration is declared, not independently measured; [] only without support inputs.\nPredictor independently assesses intervals; supported reports need analysis_basis. Concern/uncertain may use [] without endorsement; [] for liquid/no-rate reviews. No automatic data/control exclusions; recalculation/grounded premise revision remains model-owned."

def schema(name, description, properties, required=None):
    return {'type': 'function', 'function': {'name': name, 'description': description, 'parameters': {'type': 'object', 'properties': properties, 'required': list(properties) if required is None else required, 'additionalProperties': False}}}

def camera_window_tool():
    return schema('read_camera_window', 'Read all acquired records in a chosen fixed time range, paginated without quality filtering. Use camera_archive_index and command times to locate earlier courses; no new acquisition.', {'location': {'type': 'string'}, 'from_s': {'type': 'number'}, 'through_s': {'type': 'number'}, 'offset': {'type': 'integer', 'minimum': 0}, 'limit': {'type': 'integer', 'minimum': 1, 'maximum': 64}})
ACTION_INVENTORY = ' Before proposing or reviewing transfer/mix, state expected_volumes for\nexactly the affected source and target, or the mix location. These are the CURRENT volumes in\npublic estimated_inventory_ul before this one operation, not the planned final volumes or a claim\nof observed contents. A blank-like camera frame does not establish an empty vessel. Reconcile the\nexisting preparation and completed operations with the purpose of the proposed additional work;\nread_action_history can resolve earlier additions and mixing. Intentional additions, withdrawals,\ndilution, repeated mixing and recovery remain valid when grounded in the current state. Predictor\nalso receives action_preparations for the affected locations. Review its nominal premises together\nwith independent camera evidence; do not infer physical identity or placement from accounting.\nFor report review use expected_volumes=[]; there is no proposed liquid operation.'
REASONER += ACTION_INVENTORY
PREDICTOR += ACTION_INVENTORY
REASONER += '\n' + EXPERIMENT_PRACTICE
PREDICTOR += '\n' + EXPERIMENT_PRACTICE
COLOR_REASONER = REASONER
COLOR_PREDICTOR = PREDICTOR
KINETIC_REASONER = ' Register kinetic exclusions with record_evidence_decision:\naffected IDs must belong to the declared target; citations may span locations. Reinstatement needs\nreasons/acquired evidence. An exploratory interval is not an exclusion. Before discarding or replacing a course after restricted-window failure,\ncheck prior calculations and read the earlier acquired measurements; the full history may differ.\n'
REASONER += KINETIC_REASONER + CONDITION_GUIDANCE + ANALYSIS_BASIS
PREDICTOR += CONDITION_GUIDANCE + ANALYSIS_BASIS

def role_tools(role, domain):
    string = {'type': 'string'}
    number = {'type': 'number'}
    strings = {'type': 'array', 'items': string}
    expected_volumes = {'type': 'array', 'maxItems': 2, 'items': {'type': 'object', 'properties': {'location': string, 'volume_ul': {**number, 'minimum': 0}}, 'required': ['location', 'volume_ul'], 'additionalProperties': False}}
    references = {'type': 'array', 'items': {'type': 'object', 'properties': {'location': string, 'measurement_ids': {**strings, 'minItems': 1, 'uniqueItems': True}}, 'required': ['location', 'measurement_ids'], 'additionalProperties': False}}
    shared = [schema('read_retrieval_receipt', 'Immutable receipt reads: null ID indexes; JSON-pointer path="" is root. No acquisition, action or adoption.', {'receipt_event_id': {'type': ['string', 'null']}, 'path': string, 'offset': {'type': 'integer', 'minimum': 0}, 'limit': {'type': 'integer', 'minimum': 1, 'maximum': 64}}), schema('release_retrievals', 'Release working receipts only; evidence, decisions and concerns persist. Invalid IDs reject all. No action.', {'receipt_event_ids': {**strings, 'minItems': 1, 'maxItems': 8, 'uniqueItems': True}}), schema('read_shared_events', 'Read immutable public events: IDs or page([]), offset0+, limit1..64. No action.', {'event_ids': {**strings, 'uniqueItems': True}, 'offset': {'type': 'integer', 'minimum': 0}, 'limit': {'type': 'integer', 'minimum': 1, 'maximum': 64}}), schema('read_context_details', 'Snapshot pages: null/0 starts; continue snapshot_id/next_offset. Expired IDs reject. Originals stay readable.', {'section': {'type': 'string', 'enum': list(DETAIL_SECTIONS)}, 'offset': {'type': 'integer', 'minimum': 0}, 'limit': {'type': 'integer', 'minimum': 1, 'maximum': 64}, 'snapshot_id': {'type': ['string', 'null']}}), schema('find_acquired_observations', 'Find acquired timing matches at chosen locations. preparation_context_ids=[] includes all historical preparations. No acquisition or scientific approval.', {'locations': {**strings, 'minItems': 1, 'uniqueItems': True}, 'preparation_context_ids': {**strings, 'uniqueItems': True}, 'comparison_timing': timing_schema()}), schema('read_measurements', 'Chronological acquired pages with nominal preparation; no quality filter. Defaults0/64; follow next_offset. Fixed ranges: read_camera_window. Commands do not verify composition/onset.', {'location': string, 'offset': {'type': 'integer', 'minimum': 0}, 'limit': {'type': 'integer', 'minimum': 1, 'maximum': 64}}, required=['location'])]
    shared += [schema('consult_knowledge', 'Scientific priors: optics, pigment/light mixing, dilution, enzyme kinetics/units, controls, calibration, design and timing. Not observations.', {'question': string})]
    shared += [schema('read_action_history', 'Acknowledged location actions/times, not measured contents.', {'location': string}), schema('read_operation_observations', 'Index(null ID) or pre/during/post-command camera windows; []locations=all. Trace order; read-only, no causal inference.', {'command_event_id': {'type': ['string', 'null']}, 'locations': {**strings, 'uniqueItems': True}, 'offset': {'type': 'integer', 'minimum': 0}, 'limit': {'type': 'integer', 'minimum': 1, 'maximum': 24}})]
    shared += [t for t in utility_schemas(include_color=domain == 'color') if t['function']['name'] not in ('analyze_color_difference', 'simulate_observed_color_mix', 'analyze_observed_color_range', 'analyze_initial_rate', 'analyze_mm_rates')]
    if domain == 'color':
        shared.append(schema('analyze_measured_color', 'Compare acquired camera measurements to a declared calibration standard or acquired reference using CIE76. Set exactly one of target_standard and target_measurement_id; set the other to null. Supply measurement IDs, not manually copied RGB/BGR channels. The tool retains original RGB, location, time and clipping flags; it does not diagnose chemistry.', {'measurement_ids': strings, 'target_standard': {'type': ['string', 'null']}, 'target_measurement_id': {'type': ['string', 'null']}}))
    if domain == 'color':
        shared.append(schema('analyze_measured_color_range', 'Conditional RGB-model CIE76 range from two acquired IDs and first-source fraction_bounds. Choose one target; assess applicability. Validation fractions are nominal. Bounds/witness are not physical validation, outcomes or approval.', {'source_measurement_ids': {'type': 'array', 'items': string, 'minItems': 2, 'maxItems': 2}, 'fraction_bounds': {'type': 'array', 'minItems': 2, 'maxItems': 2, 'items': {'type': 'number', 'minimum': 0, 'maximum': 1}}, 'target_standard': {'type': ['string', 'null']}, 'target_measurement_id': {'type': ['string', 'null']}, 'model': {'type': 'string', 'enum': ['volume_weighted_encoded_rgb_approximation']}, 'model_applicability': {'type': 'string', 'minLength': 1, 'maxLength': 4096}, 'validation_samples': {'type': 'array', 'minItems': 0, 'maxItems': 256, 'items': {'type': 'object', 'properties': {'measurement_id': string, 'first_fraction': {'type': 'number', 'minimum': 0, 'maximum': 1}}, 'required': ['measurement_id', 'first_fraction'], 'additionalProperties': False}}}))
    if domain == 'color':
        shared.append(schema('simulate_measured_color_mix', 'Predict a hypothetical volume-weighted RGB blend from acquired source measurement IDs. This approximation does not establish physical optical mixing or an observed product. Optionally choose one declared target_standard or acquired target_measurement_id; set unused references to null (both null means no target comparison).', {'components': {'type': 'array', 'items': {'type': 'object', 'properties': {'measurement_id': string, 'volume_ul': number}, 'required': ['measurement_id', 'volume_ul'], 'additionalProperties': False}}, 'target_standard': {'type': ['string', 'null']}, 'target_measurement_id': {'type': ['string', 'null']}}))
    if domain == 'enzyme':
        shared.append(schema('analyze_measured_course', 'Calculate an initial rate from ALL acquired observations in a contiguous, unchanged preparation interval. interval_basis selects the acknowledged change, current-stage mix, or explicit acquired start with a rationale; it does not establish scientific validity. Null through_measurement_id uses the latest observation; null from_measurement_id uses the chosen boundary (explicit_interval requires a start ID). Conflicting anchors are rejected; preceding and censored observations remain disclosed. Uses exact timestamps, recorded OD, declared optics and nominal concentrations, selecting the longest initial prefix meeting public quality criteria. Supply acquired enzyme-free blanks matching nominal volume/substrate, stock references and OD limit; mass conversion needs declared molecular_weight_kDa. No substitute blanks are selected. Returns bound inputs and calculation ID. A changed temporal premise needs a new calculation. Interpret chemical suitability and uncertainty; fit agreement alone is insufficient.', {'location': string, 'interval_basis': {'type': 'object', 'properties': {'basis': {'type': 'string', 'enum': ['after_preparation_change', 'after_preparation_mix', 'explicit_interval']}, 'rationale': string}, 'required': ['basis', 'rationale'], 'additionalProperties': False}, 'from_measurement_id': {'type': ['string', 'null']}, 'through_measurement_id': {'type': ['string', 'null']}, 'blank_measurement_ids': strings, 'substrate_stock': string, 'enzyme_stock': string, 'od_linear_max': number}))
        shared.append(schema('analyze_measured_mm_rates', 'Fit apparent Michaelis-Menten parameters from selected recorded qualifying rate calculation IDs. Rates, substrate/enzyme concentrations and well identities are read from those results, not copied. Multiple calculations of one well do not count as independent replication. Returns source rows and replicate counts; interpret fit quality and limitations using public requirements.', {'rate_calculation_ids': strings}))
    if domain == 'enzyme':
        shared.append(schema('analyze_measured_endpoint_series', 'Summarize acquired endpoint IDs in native stock units. One concentration returns mean/SD/CV and readout precision with status insufficient_data and null regression fields: not an adoptable curve. Two or more concentrations permit a fit. Select one endpoint per nominal preparation; explain comparison and controls. after_last_mix requires mixing after material change. subtract_mean needs zero-stock controls of matching volume; none needs no blanks. Recorded arithmetic is not independence, applicability, quality acceptance or task success. Cite calculation_id for fit adoption.', {'measurement_ids': strings, 'blank_measurement_ids': strings, 'concentration_stock': string, 'blank_correction': {'type': 'string', 'enum': ['none', 'subtract_mean']}, 'time_basis': {'type': 'string', 'enum': ['after_last_addition', 'after_last_mix', 'captured_at_s']}, 'comparison_rationale': string, 'comparison_timing': endpoint_timing_schema()}, required=['measurement_ids', 'blank_measurement_ids', 'concentration_stock', 'blank_correction', 'time_basis', 'comparison_rationale']))
    if domain == 'enzyme' and role == 'reasoner':
        shared.append(schema('record_evidence_decision', 'Record kinetic exclusions/reinstatements: target location, its acquired IDs, rationale and acquired evidence (possibly elsewhere). Persists for reaction/blank inputs; records stay. Only excluded IDs may be reinstated. Interval selection needs no exclusion. No execution, chemistry choice or quality change.', {'location': string, 'measurement_ids': strings, 'decision': {'type': 'string', 'enum': ['exclude', 'reinstate']}, 'rationale': string, 'evidence_ids': strings}))
    if domain == 'enzyme' and role == 'reasoner':
        shared.append(schema('respond_to_analysis_advice', 'Dispose pending acquired-data analysis proposals, individually or as a justified group. Accept records exclusions; reject keeps measurements available with your acquired evidence and rationale. Neither authorizes liquid work nor overrides safety. Already resolved advice cannot be disposed again.', {'advice_ids': strings, 'decision': {'type': 'string', 'enum': ['accept', 'reject']}, 'rationale': string, 'evidence_ids': strings}))
    if role == 'predictor':
        return shared + [schema('submit_review', 'Record a scientific review with acquired observation references and optional testable expectations.', {'observation_references': references, 'expected_volumes': expected_volumes, 'verdict': {'type': 'string', 'enum': ['supported', 'concern', 'uncertain']}, 'rationale': string, **({'analysis_basis': basis_schema(), 'analysis_exclusions': {'type': 'array', 'items': {'type': 'object', 'properties': {'location': string, 'measurement_ids': {**strings, 'minItems': 1, 'uniqueItems': True}, 'evidence_ids': {**strings, 'minItems': 1, 'uniqueItems': True}, 'rationale': string}, 'required': ['location', 'measurement_ids', 'evidence_ids', 'rationale'], 'additionalProperties': False}}} if domain == 'enzyme' else {}), 'expectations': {'type': 'array', 'items': {'type': 'object', 'properties': {'location': string, 'field': {'type': 'string', 'enum': ['od_estimate', 'captured_at_s', 'rgb_0', 'rgb_1', 'rgb_2']}, 'lower': number, 'upper': number}, 'required': ['location', 'field', 'lower', 'upper'], 'additionalProperties': False}}})]
    return shared + [schema('resolve_review_concern', 'Resolve accepted advice with grounds. For canonical report claims, [] permits logical correction; otherwise cite acquired evidence. No execution, exclusions or new review.', {'review_id': string, 'decision': {'type': 'string', 'enum': ['resolved', 'reject']}, 'rationale': string, 'evidence_ids': {**strings, 'uniqueItems': True}}), schema('transfer', 'Propose transfer now for automatic Predictor review. Supported proposals execute through Actor after safety checks; respond to concerns first. Do not wait for review before proposing.', {'source': string, 'target': string, 'volume_ul': number, 'expected_volumes': expected_volumes}), schema('mix', 'Propose mixing for automatic Predictor review. Supported proposals execute through Actor after safety checks; respond to concerns first.', {'location': string, 'volume_ul': number, 'expected_volumes': expected_volumes}), schema('wait', 'Advance the experimental clock in seconds.', {'seconds': number}), schema('inspect', 'Acquire a camera frame at declared locations.', {'locations': strings}), schema('record_decision', 'Revise decision only; keep plan/timing/cohorts. No execution. First use record_plan.', {'decision': decision_update_schema()}), schema('record_plan', 'Store plan/timing/cohort notes; no action authorization. Action tools request pre-execution review.', {'plan': string, 'observation_references': references, 'decision': decision_schema(), 'comparison_timing': timing_schema(), 'acquisition_locations': {**strings, 'uniqueItems': True, 'description': 'Locations for chosen timing; omitted/[] clears scope. No default timing premise.'}, 'cohort_updates': {'type': 'array', 'items': {'type': 'object', 'properties': {'cohort_id': string, 'purpose': {'type': 'string', 'enum': ['report_candidate', 'diagnostic', 'control']}, 'rationale': string, 'members': {'type': 'array', 'minItems': 1, 'items': {'type': 'object', 'properties': {'member_id': string, 'location': string, 'preparation_id': {'type': ['string', 'null'], 'description': 'Intended completed stage: location@last_change_event_id; null while assembling. Immutable; mixing is not a new preparation.'}, 'disposition': {'type': 'string', 'enum': ['pending', 'nonadopt']}, 'rationale': string, 'evidence_ids': {**strings, 'description': ACQUIRED_IDS_DESCRIPTION}}, 'required': ['member_id', 'location', 'preparation_id', 'disposition', 'rationale', 'evidence_ids'], 'additionalProperties': False}}}, 'required': ['cohort_id', 'purpose', 'rationale', 'members'], 'additionalProperties': False}, 'description': 'Changed members only; others persist. Immutable purpose/binding. Explain nonadopt/reinstate. Diagnostic/control: advisory, no auto-exclusion.'}}, required=['plan', 'observation_references']), schema('respond_to_review', 'Only proceed authorizes execution; accept/revise/reject withdraw. acknowledge retains the queue without execution. Evidence and safety bind; canonical report logic permits rejection with [].', {'review_id': string, 'decision': {'type': 'string', 'enum': ['proceed', 'reject', 'accept', 'revise', 'acknowledge']}, 'rationale': string, 'evidence_ids': strings}), schema('manage_pending_action', 'Proceed/withdraw by exact held-action ID. Proceed needs evidence, disposed reviews, unchanged decision/inventory and safety. Withdrawal leaves advice pending.', {'action_id': string, 'decision': {'type': 'string', 'enum': ['proceed', 'withdraw']}, 'rationale': string, 'evidence_ids': strings}), schema('finish', 'Report a conclusion or justified stop with acquired IDs. Configured Predictor review checks report support and ending the original task; revise or reaffirm concerns with grounds. No grade or liquid execution.', {'conclusion': string, 'measurement_ids': strings, 'task_resolution': {'anyOf': [*decision_schema(compact_basis=True)['anyOf'], decision_update_schema()]}, **({'adopted_measurement_ids': {**strings, 'description': 'Adopted final color observations. measurement_ids may cite diagnostics; citation alone does not adopt reporting members.'}} if domain == 'color' else {}), **({'calculation_ids': strings, 'analysis_basis': basis_schema()} if domain == 'enzyme' else {})}, required=['conclusion', 'measurement_ids', 'task_resolution', *(['calculation_ids', 'analysis_basis'] if domain == 'enzyme' else [])])]

class ToolResponseValidationError(ValueError):
    """Local tool-envelope validation, separate from provider failures."""

class ReviewValidationError(ValueError):
    """A rejected submission retained for public scientific disposition."""

    def __init__(self, message, feedback):
        super().__init__(message)
        self.feedback = deepcopy(feedback)

class ObservationRuntime:
    planning_role = 'reasoner'
    independent_prediction = True
    require_prospective_design = False
    review_reports_before_liquid = False

    def __init__(self, world, *, chat, event_sink=None, compact_messages=False, continuous_camera_interval_s=None, monotonic=None, knowledge_factory=None, watchdog_factory=None):
        self.world = world
        self._initial_plate_total_ul = sum((volume for location, volume in world.inventory.items() if location.startswith('plate:')))
        self.chat = chat
        self.compact_messages = compact_messages
        self.board = Blackboard(event_sink=event_sink)
        self.board.planning_role = self.planning_role
        if knowledge_factory is None or watchdog_factory is None:
            raise ValueError('Explicit LLM peer composition is required')
        self.knowledge = knowledge_factory(self.board)
        self.watchdog = watchdog_factory(self.board, comparison_state=self._comparison_state, optical_calibration=world.camera.calibration)
        self.actor = Actor(world.execute)
        self.actor.camera_observations = lambda: self.board.camera_for('actor')
        self.working_plan = ''
        self.working_plan_observations = []
        self.comparison_timing = None
        self.acquisition_locations = []
        self.last_result = {}
        self.pending = []
        self._action = None
        self._action_decision_ref = None
        self._action_review = None
        self._evidence = {}
        self._context_snapshots = {}
        from pearl.runtime.retrieval_memory import RetrievalMemory
        self._retrieval_memory = RetrievalMemory()
        self._handled = set()
        self._knowledge_topics = set()
        self._has_liquid_actions = False
        self._report_reviewed = False
        self._last_report_subject = None
        self._last_report_frontier = None
        self._last_report_id = None
        self._report_revision = {}
        self.turns = 0
        self.continuous_camera = None
        if continuous_camera_interval_s is not None:
            from pearl.runtime.continuous_camera import ContinuousCamera
            self.continuous_camera = ContinuousCamera(self, continuous_camera_interval_s, monotonic)
            world.clock_driver = self.continuous_camera
            world.continuous_camera_interval_s = self.continuous_camera.interval_s

    def _start_capture(self, locations, *, request_id=None):
        self.board.publish(ObservationEvent(source_agent='actor', observation_type='camera_acquisition_started', payload={'started_at_s': self.world.time_s, 'capture_duration_s': self.world.briefing()['equipment']['capture_duration_s'], 'locations': list(locations), **({'request_id': request_id} if request_id is not None else {})}))

    def _capture(self, locations):
        if self.continuous_camera:
            return self.world.inspect(locations)
        self._start_capture(locations)
        packet = self.world.inspect(locations)
        self._evidence.update({m['measurement_id']: m for m in packet['measurements']})
        self.board.publish(ObservationEvent(source_agent='actor', observation_type='camera', payload=packet))
        self._collect_findings()
        return packet

    def _collect_findings(self):
        pending_ids = {r['event_id'] for r in self.pending}
        for event in self.watchdog.findings():
            if event.event_id not in self._handled and event.event_id not in pending_ids:
                self.pending.append(event.to_dict())
                self._retrieve_for_finding(event)

    def _comparison_state(self):
        return {'events': self.board.event_log, 'evidence': self._evidence, 'setup': self.world.briefing(), 'declaration': self.comparison_timing, 'cohorts': cohort_memory(self.board.event_log)}

    def _finding_measurements(self, event):
        acquired = {m['measurement_id']: m for m in self.board.camera_for('watchdog')['measurements']}
        acquired.update(self._evidence)
        return [acquired[mid] for mid in event.evidence.get('measurement_ids', []) if mid in acquired]

    def _finding_question(self, event, measurements):
        field = event.evidence.get('field')
        if event.anomaly_id == 'forecast_mismatch' and field in ('rgb_0', 'rgb_1', 'rgb_2', 'od_estimate'):
            optical = field == 'od_estimate' or any(('od_estimate' in m for m in measurements))
            topic = 'camera absorbance measurements' if optical else 'camera intensity measurements'
            return 'Prediction and observation disagree for ' + topic + '. Discuss general measurement assumptions, uncertainty and interpretation of the public evidence.'
        return event.anomaly_id.replace('_', ' ') + ' ' + str(field or '') + '. Explain relevant scientific assumptions and limitations.'

    def _retrieve_for_finding(self, event):
        measurements = self._finding_measurements(event)
        topic = self._finding_question(event, measurements)
        if topic in self._knowledge_topics:
            return
        answer = self._knowledge('watchdog', {'question': topic}, observation={'evidence_ids': [m['measurement_id'] for m in measurements], 'measurements': measurements})
        self._retrieval_memory.remember('consult_knowledge', {'question': topic}, answer, answer['event_id'])
        self._knowledge_topics.add(topic)

    def _action_workflow(self):
        workflow = {'review_waiting_for_response': bool(self.pending), 'liquid_proposal_tools': ['transfer', 'mix'], 'record_plan_requests_review': False, 'sequence': 'transfer/mix proposal -> Predictor review -> response if needed -> safety admission -> Actor execution -> camera', 'meaning': 'No asynchronous review starts from planning notes. Submit an action only when scientifically ready; observation, calculation, revision and justified stopping remain available.'}
        from pearl.runtime.initial_plan import enabled, adopted_design_exists
        if enabled(self):
            initial = not adopted_design_exists(self)
            workflow['record_plan_requests_review'] = initial
            workflow['initial_design'] = {'state': 'proposal_before_adoption' if initial else 'adopted', 'adoption_tool': 'adopt_reviewed_plan', 'scope': 'Initial whole design only; routine progress retains the existing workflow. Review and adoption are not operation authorization.'}
            workflow['meaning'] = 'Initial record_plan with a scientific decision stages an immutable design and obtains review before explicit author adoption. Notes without a decision stay nonactive. Action proposals retain separate scientific and execution checks; information gathering and justified stopping remain available.'
        return workflow

    def _context(self, role, **extra):
        if self.continuous_camera:
            self.continuous_camera.drain()
        from pearl.runtime.acquisition_schedule import pending_schedule
        from pearl.runtime.color_memory import color_comparison_memory
        from pearl.runtime.report_review import computation_index
        computations = computation_index(self.board.event_log)
        comparisons = color_comparison_memory(self.board.event_log, self._evidence, self.world.briefing()['reagents'])
        events = self.board.public_events(excluded_observation_types=('camera', REJECTION_TYPE))
        camera = self.board.camera_for(role)
        plan_acquisition = acquisition_context(self.working_plan_observations, self.board.event_log, self.world.briefing()['reagents']) if self.working_plan_observations else {'captures': [], 'preparations': []}
        current_ids = {m['measurement_id'] for m in camera['measurements']}
        cohorts = cohort_memory(self.board.event_log)
        retrieval = self._retrieval_memory.view()
        active_decision = current_decision(self.board.event_log)
        rejected = rejected_memory(self.board.event_log, active_decision['event_id'] if active_decision else None)
        context = {**({'computation_history': computations} if computations['total'] else {}), **({'rejected_decision_memory': rejected} if rejected is not None else {}), **({'color_comparison_memory': comparisons} if comparisons else {}), **({'camera_archive_index': self.continuous_camera.archive_index()} if self.continuous_camera else {}), 'setup': self.world.briefing(), 'time_s': self.world.time_s, 'camera': camera, 'measurement_history': [m for m in list(self._evidence.values())[-192:] if m['measurement_id'] not in current_ids], 'commanded_preparations': preparation_summary(self.board.event_log, self.world.briefing()['reagents']), 'operation_state': operation_state(self.board.event_log), 'omitted_earlier_measurements': max(0, len(self._evidence) - 192), 'estimated_inventory_ul': deepcopy(self.world.inventory), 'plate_transfer_accounting': plate_transfer_accounting(self.board.event_log, self._initial_plate_total_ul), **({'working_plan_timing': timing_context(self.comparison_timing, plan_acquisition)} if self.comparison_timing is not None else {}), 'working_plan': self.working_plan, **({'decision_memory': current_decision(self.board.event_log)} if current_decision(self.board.event_log) else {}), **({'cohort_memory': cohorts} if cohorts else {}), **({'pending_schedule': pending_schedule(self.board.event_log, self._evidence, self.world.briefing(), self.world.time_s, cohorts, extra.get('proposed_action'))} if cohorts else {}), **({'acquisition_schedule': acquisition_schedule(self.acquisition_locations, self.comparison_timing, self.board.event_log, self._evidence, self.world.briefing(), self.world.time_s)} if self.acquisition_locations and self.comparison_timing is not None else {}), 'working_plan_observations': deepcopy(self.working_plan_observations), **({'working_plan_acquisition_context': plan_acquisition} if self.working_plan_observations else {}), **({'analysis_memory': analysis_memory(self.board.event_log, self._evidence), 'recorded_analysis_intervals': adoption_intervals([e.result['calculation_id'] for e in self.board.event_log if getattr(e, 'tool_name', None) in ('analyze_measured_course', 'analyze_measured_initial_rate') and e.result.get('status') == 'ok' and e.result.get('calculation_id')], self.board.event_log, self._evidence)} if self.world.briefing()['domain'] == 'enzyme' else {}), **shared_message_context(events), 'pending_reviews': deepcopy(self.pending), 'pending_action': {'action_id': self._action[0].action_id, 'name': self._action[0].action_type, 'arguments': public_copy(self._action[0].params), 'plan_id': self._action[1], 'decision_ref': self._action_decision_ref, 'status': 'held'} if self._action is not None else None, 'scientific_review_memory': review_memory(self.board.event_log), 'action_workflow': self._action_workflow(), 'last_tool_result': deepcopy(self.last_result), **({'retrieval_memory': retrieval} if retrieval['entries'] or retrieval['last_omission'] or retrieval['last_release'] else {}), **extra}
        requirements = replication_requirement_scope(context['setup'])
        if requirements is not None:
            context['replication_requirement_scope'] = requirements
        from pearl.runtime.requirement_provenance import requirement_scope
        context['requirement_scope'] = requirement_scope(context['setup'], context.get('decision_memory'))
        history = evidence_history_view(self.board.event_log, self._evidence, context)
        if history is not None:
            context['evidence_history_view'] = history
        return context

    def _role_tools(self, role):
        return role_tools(role, self.world.domain)

    def _system_prompt(self, role):
        if self.world.domain == 'color':
            return COLOR_REASONER if role == 'reasoner' else COLOR_PREDICTOR
        return REASONER if role == 'reasoner' else PREDICTOR

    def _prepare_messages(self, role, messages):
        return messages

    def _finalize_tools(self, role, tools):
        return tools

    def _delivery_context(self, canonical, role):
        return project_context(canonical, role) if self.compact_messages else canonical

    def _call(self, role, **extra):
        canonical = self._context(role, **extra)
        from pearl.runtime.initial_plan import enabled, context as initial_plan_context, adoption_tool
        if enabled(self) and role == self.planning_role and ('review_workflow' not in extra):
            initial = initial_plan_context(self)
            if initial is not None:
                canonical['initial_design_proposal'] = initial
        context = self._delivery_context(canonical, role)
        if 'evidence_history_view' in canonical:
            from pearl.runtime.retrieval_memory import receipt_reference
            cursor = uuid.uuid4().hex
            section = 'evidence_history_view.units'
            self._retrieval_memory.archive('delivered_evidence_history', {'section': section}, canonical['evidence_history_view'], cursor)
            context['evidence_history_view']['full_history_read'] = receipt_reference(cursor)
        lookup = context.get('evidence_history_view', {}).get('remaining_units_read')
        if lookup is not None:
            self._context_snapshots[cursor] = (section, {'evidence_history_view': {'units': deepcopy(canonical['evidence_history_view']['units'])}})
            if len(self._context_snapshots) > 16:
                self._context_snapshots.pop(next(iter(self._context_snapshots)))
            lookup['arguments'].update(offset=lookup['next_omitted_offset'], snapshot_id=cursor)
            lookup['paging'] = 'Read omitted units from this exact delivered snapshot; use the returned snapshot_id for further pages. Normal bounded snapshot expiry applies. A new snapshot may have different decision scope.'
            lookup['durable_read'] = receipt_reference(cursor, '/units', lookup['next_omitted_offset'])
            context['evidence_history_view']['acquisition_context'] = receipt_reference(cursor, '/acquisition_context')
        if self.compact_messages:
            reference_context_collections(context, role, self._retrieval_memory)
        context = order_context(context)
        messages = [{'role': 'system', 'content': self._system_prompt(role) + ('\n' + TABLE_GUIDE if self.compact_messages else '')}, {'role': 'user', 'content': json.dumps(compact_context(context) if self.compact_messages else context, allow_nan=False, separators=(',', ':'))}]
        if role == 'predictor' and 'proposed_report' in extra:
            messages[0]['content'] = messages[0]['content'].replace(ACTION_INVENTORY, ' Report review uses expected_volumes=[]. Command records are not acquired verification; assess images only for the properties they measure.').replace(CAPTURE_FORECAST, '')
        tools = self._role_tools(role)
        if enabled(self) and role == self.planning_role and ('review_workflow' not in extra):
            tools.append(adoption_tool())
            messages[0]['content'] = messages[0]['content'].replace('record_plan stores notes only; it neither submits nor starts review.', 'Initial record_plan stages a design for review; explicit adoption is separate from execution.')
            messages[0]['content'] += ' Before the first scientific design is adopted, record_plan stages an immutable proposal for the configured scientific reviewer. It does not activate a design, timing or cohorts. Review the returned assessment, obtain information or revise as needed, then explicitly adopt the exact reviewed proposal with adopt_reviewed_plan and your scientific grounds. Agreement is not mandatory. Public-premise reasoning may cite []; no calculation, measurement or successful outcome is prescribed. Ordinary notes stay nonactive. After initial adoption, routine plan updates retain the existing workflow.'
        if self.continuous_camera:
            transfer_tool = next((t['function'] for t in tools if t['function']['name'] == 'transfer'), None)
            if transfer_tool is not None:
                transfer_tool['parameters']['properties']['mix_after_transfer_ul'] = {'type': ['number', 'null']}
                transfer_tool['parameters']['required'].append('mix_after_transfer_ul')
                transfer_tool['description'] += ' Optionally request immediate destination mixing with mix_after_transfer_ul; null means transfer only. Predictor reviews the entire request; Actor records and validates both operations without an intervening model call.'
            tools.append(camera_window_tool())
        if role == 'predictor' and extra.get('review_workflow', {}).get('phase') in ('decision', 'correction'):
            tools = [t for t in tools if t['function']['name'] == 'submit_review']
        if role == 'predictor' and ('decision_subject_id' in extra or 'proposed_report' in extra):
            review_schema = next((t['function']['parameters'] for t in tools if t['function']['name'] == 'submit_review'))
            if 'proposed_report' in extra:
                review_schema['properties']['task_resolution'] = resolution_schema()
                review_schema['required'].append('task_resolution')
            review_schema['properties']['decision_assessment'] = assessment_schema(proposed_report=extra.get('proposed_report'), proposed_decision=extra.get('proposed_decision'))
            review_schema['required'].append('decision_assessment')
        if role == 'predictor':
            review_schema = next((t['function']['parameters'] for t in tools if t['function']['name'] == 'submit_review'), None)
            if review_schema is not None:
                decision_review = isinstance(extra.get('proposed_decision'), dict)
                report_review = isinstance(extra.get('proposed_report'), dict)
                proposal = extra.get('proposed_action')
                liquid_review = isinstance(proposal, dict) and proposal.get('name') in ('transfer', 'mix')
                if decision_review or report_review:
                    for field in ('expected_volumes', 'expectations'):
                        review_schema['properties'][field]['maxItems'] = 0
                        review_schema['properties'][field]['items'] = {'type': 'object', 'properties': {}, 'required': [], 'additionalProperties': False}
                empty_adoption = report_review and extra.get('adopted_analysis_intervals') == []
                if self.world.domain == 'enzyme' and (decision_review or liquid_review or empty_adoption):
                    review_schema['properties']['analysis_basis']['maxItems'] = 0
                    review_schema['properties']['analysis_basis']['items'] = {'type': 'object', 'properties': {}, 'required': [], 'additionalProperties': False}
            tools = [strict_function_tool(t) if t['function']['name'] == 'submit_review' else t for t in tools]
        tools = self._finalize_tools(role, tools)
        if self.require_prospective_design:
            tools = deepcopy(tools)
            for tool in tools:
                function = tool['function']
                if function['name'] in ('transfer', 'mix'):
                    function['description'] += ' Before liquid work, record_plan must establish your prospective scientific decision and its goal/model or diagnostic basis.'
                elif function['name'] == 'record_plan':
                    function['description'] += ' Supply the prospective decision before liquid work; explain the whole experiment and available model implications or justified diagnostic question.'
        messages = self._prepare_messages(role, messages)
        result = self.continuous_camera.call(role, lambda: self.chat(role, messages, tools)) if self.continuous_camera else self.chat(role, messages, tools)
        if not isinstance(result, dict) or not isinstance(result.get('name'), str) or (not isinstance(result.get('arguments'), dict)):
            raise ToolResponseValidationError('Return one tool name and argument object')
        permitted = {t['function']['name'] for t in tools}
        if result['name'] not in permitted:
            raise ToolResponseValidationError('Tool is not available to this role')
        if result['name'] == 'analyze_measured_course' and 'interval_basis' not in result['arguments']:
            raise ToolResponseValidationError('Choose interval_basis explicitly for a new course calculation; no temporal premise was inferred')
        return (result['name'], result['arguments'])

    def _knowledge(self, role, p, *, observation=None):
        question = p['question']
        if not isinstance(question, str) or not question.strip():
            raise ValueError('A question is required')
        camera = self.board.camera_for(role) if observation is None else observation
        request = KnowledgeRequestEvent(source_agent=role, request_id=uuid.uuid4().hex, goal=question, observation={'evidence_ids': camera['evidence_ids'], 'observations': camera['measurements'], 'provenance': 'shared acquired camera evidence'})
        self.board.publish(request)
        answers = [e for e in self.board.event_log if isinstance(e, KnowledgeResponseEvent) and e.request_id == request.request_id]
        if len(answers) != 1 or answers[0].audit.get('error'):
            raise RuntimeError('Knowledge response delivery failed')
        return answers[0].to_dict()

    def _read_detail_page(self, role, args):
        if not isinstance(args, dict) or set(args) != {'section', 'offset', 'limit', 'snapshot_id'}:
            raise ValueError('Provide section, offset, limit and snapshot_id')
        cursor = args['snapshot_id']
        page_args = {k: args[k] for k in ('section', 'offset', 'limit')}
        if cursor is None:
            if args['offset'] != 0:
                raise ValueError('Start a new context snapshot at offset zero')
            context = self._context(role)
            result = read_context_details(context, page_args)
            cursor = uuid.uuid4().hex
            self._context_snapshots[cursor] = (args['section'], deepcopy(context))
            if len(self._context_snapshots) > 16:
                self._context_snapshots.pop(next(iter(self._context_snapshots)))
        else:
            if not isinstance(cursor, str) or not cursor or cursor not in self._context_snapshots:
                raise ValueError('Unknown or expired context snapshot')
            section, context = self._context_snapshots[cursor]
            if args['section'] != section:
                raise ValueError('A context snapshot belongs to its original section')
            result = read_context_details(context, page_args)
        return {**result, 'snapshot_id': cursor}

    def _utility(self, role, name, args):
        from pearl.runtime.retrieval_memory import RETRIEVAL_TOOLS
        result = self._execute_utility(role, name, args)
        if name in RETRIEVAL_TOOLS:
            self._retrieval_memory.remember(name, args, result, self.board.event_log[-1].event_id)
        return result

    def _execute_utility(self, role, name, args):
        if name == 'analyze_observed_color_range':
            raise ValueError('Use acquired measurement references for color range analysis')
        if name == 'analyze_measured_color_range':
            if self.world.domain != 'color':
                raise ValueError('The selected range model is a color analysis tool')
            result = measured_color_range(args, self._evidence, self.world.briefing()['calibration']['color_standards'])
            self.board.publish(ToolCallEvent(source_agent=role, tool_name=name, params=deepcopy(args), result=deepcopy(result), executed=False))
            return result
        if name == 'read_retrieval_receipt':
            result = self._retrieval_memory.read(args)
            self.board.publish(ToolCallEvent(source_agent=role, tool_name=name, params=deepcopy(args), result=archive_receipt(result), executed=False))
            return result
        if name == 'release_retrievals':
            if not isinstance(args, dict) or set(args) != {'receipt_event_ids'}:
                raise ValueError('Provide only receipt_event_ids for retrieval release')
            result = self._retrieval_memory.release(args['receipt_event_ids'])
            self.board.publish(ToolCallEvent(source_agent=role, tool_name=name, params=deepcopy(args), result=deepcopy(result), executed=False))
            return result
        if name == 'read_camera_window' and self.continuous_camera:
            result = self.continuous_camera.read_window(args)
            self.board.publish(ToolCallEvent(source_agent=role, tool_name=name, params=deepcopy(args), result={'measurement_ids': [m['measurement_id'] for m in result['measurements']], 'total': result['total'], 'next_offset': result['next_offset'], 'scope': 'Exact detached window delivered; raw frames retained.'}, executed=False))
            return result
        if name in ('read_shared_events', 'read_context_details'):
            result = read_shared_events(self.board.event_log, args) if name == 'read_shared_events' else self._read_detail_page(role, args)
            self.board.publish(ToolCallEvent(source_agent=role, tool_name=name, params=deepcopy(args), result=archive_receipt(result), executed=False))
            return result
        if name == 'resolve_review_concern':
            return resolve_concern(self.board, role, args, self._evidence)
        if name == 'find_acquired_observations':
            result = find_observations(args, self._evidence, self.board.event_log, self.world.briefing(), self.world.inventory)
            self.board.publish(ToolCallEvent(source_agent=role, tool_name=name, params=deepcopy(args), result=deepcopy(result), executed=False))
            return result
        if name == 'respond_to_analysis_advice':
            if self.world.domain != 'enzyme':
                raise ValueError('Analysis advice applies to enzyme experiments')
            return respond_analysis_advice(self.board, role, args, self._evidence)
        if name == 'record_evidence_decision':
            if self.world.briefing()['domain'] != 'enzyme':
                raise ValueError('Kinetic evidence decisions require an enzyme experiment')
            return record_decision(self.board, role, args, self._evidence)
        if name == 'calculate_capacity_bound':
            raise ValueError('Unknown utility: calculate_capacity_bound is offline-only')
        if name == 'consult_knowledge':
            return self._knowledge(role, args)
        if name == 'read_operation_observations':
            from pearl.runtime.operation_observations import read_operation_observations
            result = read_operation_observations(self.board.event_log, args, self.world.inventory)
            self.board.publish(ToolCallEvent(source_agent=role, tool_name=name, params=deepcopy(args), result=deepcopy(result), executed=False))
            return result
        if name == 'read_action_history':
            if args['location'] not in self.world.inventory:
                raise ValueError('Unknown location')
            result = {'basis': 'Acknowledged commands, not independently observed contents', 'actions': action_history(self.board.event_log, args['location'], self.world.briefing()['reagents'])}
            self.board.publish(ToolCallEvent(source_agent=role, tool_name=name, params=args, result=result, executed=False))
            return result
        if name == 'read_measurements':
            if set(args) - {'location', 'offset', 'limit'}:
                raise ValueError('Choose location and optional offset/limit')
            if args['location'] not in self.world.inventory:
                raise ValueError('Unknown location')
            offset, limit = (args.get('offset', 0), args.get('limit', 64))
            if type(offset) is not int or offset < 0 or type(limit) is not int or (not 1 <= limit <= 64):
                raise ValueError('Nonnegative offset and limit 1..64 required')
            measurements = [m for m in self._evidence.values() if m['location'] == args['location']]
            total = len(measurements)
            measurements = measurements[offset:offset + limit]
            result = {'measurements': deepcopy(measurements), 'total': total, 'offset': offset, 'next_offset': offset + limit if offset + limit < total else None, 'acquisition_context': acquisition_context(measurements, self.board.event_log, self.world.briefing()['reagents'])}
            self.board.publish(ToolCallEvent(source_agent=role, tool_name=name, params=args, result=result, executed=False))
            return result
        if name == 'analyze_measured_endpoint_series':
            if self.world.domain != 'enzyme':
                raise ValueError('Endpoint optical series requires an enzyme assay')
            selected_args = {k: v for k, v in args.items() if k != 'comparison_timing'}
            result = measured_endpoint_series(selected_args, self._evidence, self.board.event_log, self.world.briefing())
            audit = endpoint_timing_audit(args.get('comparison_timing'), 'comparison_timing' in args, self.comparison_timing, self.working_plan_observations, list(dict.fromkeys(selected_args['measurement_ids'] + selected_args['blank_measurement_ids'])), result['acquisition_context'])
            if audit is not None:
                result['comparison_timing_audit'] = audit
            result['calculation_id'] = uuid.uuid4().hex
            self.board.publish(ToolCallEvent(source_agent=role, tool_name=name, params=deepcopy(args), result=deepcopy(result), executed=False))
            return result
        if name in ('analyze_measured_initial_rate', 'analyze_measured_course', 'analyze_measured_mm_rates'):
            selection = None
            selected = args
            if name == 'analyze_measured_course':
                selected, selection = select_rate_course(args, self._evidence, self.board.event_log, self.world.briefing())
            if name == 'analyze_measured_mm_rates':
                validate_adoption(args.get('rate_calculation_ids'), self.board.event_log)
            else:
                require_eligible(selected.get('measurement_ids', []) + selected.get('blank_measurement_ids', []), self.board.event_log)
            if selection is not None and len(selected['measurement_ids']) < 3:
                result = {'status': 'too_few_points', 'v0_uM_per_s': None, 'measurement_ids': selected['measurement_ids'], 'blank_measurement_ids': selected['blank_measurement_ids'], 'points_used': len(selected['measurement_ids']), 'note': 'Fewer than three uncensored observations remain in the selected preparation interval; no rate was calculated.'}
            else:
                result = measured_initial_rate(selected, self._evidence, self.board.event_log, self.world.briefing()) if name in ('analyze_measured_initial_rate', 'analyze_measured_course') else measured_mm(args, self.board.event_log, self.world.briefing())
            if selection is not None:
                result['course_selection'] = selection
                result['selection_diagnostics'] = course_selection_diagnostics(selection, result, self._evidence, self.board.event_log, self.world.briefing())
            result['calculation_id'] = uuid.uuid4().hex
            self.board.publish(ToolCallEvent(source_agent=role, tool_name=name, params=args, result=result, executed=False))
            return result
        if name == 'analyze_measured_color':
            bound = resolve_color_target(args, self._evidence, self.world.briefing()['calibration']['color_standards'])
        result = simulate_measured_mix(args, self._evidence, self.world.briefing()['calibration']['color_standards']) if name == 'simulate_measured_color_mix' else compare_measured_color(bound, self._evidence) if name == 'analyze_measured_color' else execute_utility(name, args)
        if name == 'analyze_measured_color':
            result['target_reference'] = {'standard': args['target_standard'], 'measurement_id': args['target_measurement_id'], 'lab': bound['target_lab']}
            result['evidence_status'] = 'acquired camera values and referenced public target'
        if name == 'analyze_initial_rate':
            result = explain_initial_window(result, args)
        self.board.publish(ToolCallEvent(source_agent=role, tool_name=name, params=args, result=result, executed=False))
        return result

    def _review_frontier(self):
        from pearl.runtime.report_review import report_frontier
        events = self.board.event_log
        if self.continuous_camera:
            events = [e for e in events if not (getattr(e, 'observation_type', None) == 'camera' and getattr(e, 'payload', {}).get('acquisition_mode') == 'autonomous_simulated')]
        return report_frontier(events)

    def _needs_report_review(self, report):
        from pearl.runtime.report_review import report_frontier, report_subject
        return report_subject(report) != self._last_report_subject or self._review_frontier() != self._last_report_frontier

    def _require_prospective_design(self, action):
        from pearl.runtime.initial_plan import enabled, adopted_design_exists
        if enabled(self) and action.action_type in ('transfer', 'mix') and (not adopted_design_exists(self)):
            raise ValueError('Before liquid work, propose the initial design with record_plan, consider its review and explicitly adopt it with adopt_reviewed_plan. No liquid operation was queued or authorized.')
        if self.require_prospective_design and action.action_type in ('transfer', 'mix') and (current_decision(self.board.event_log) is None):
            raise ValueError('Before selecting liquid work, use record_plan with your prospective scientific decision. Explain the whole experiment, public goal and available model implications, or the justified question and decision value of a diagnostic. No operation was queued or authorized.')

    def _action_decision_subject(self, action):
        if action.action_type not in ('transfer', 'mix'):
            return None
        current = current_decision(self.board.event_log)
        if current is None:
            return None
        subject = current['event_id']
        from pearl.runtime.initial_plan import reviewed_canonical
        if reviewed_canonical(self, subject):
            return None
        for event in self.board.event_log:
            if getattr(event, 'source_agent', None) == 'predictor' and getattr(event, 'observation_type', None) == 'scientific_review' and ((event.payload.get('decision_assessment') or {}).get('subject_id') == subject):
                return None
        return subject

    def _review(self, action, plan_id):
        from pearl.runtime.report_review import computation_context
        failures = 0
        invalid = None
        for attempt in range(5):
            proposal = {'proposed_report': public_copy(action.params), 'report_id': plan_id, 'decision_subject_id': action.params.get('decision_ref') or plan_id} if action.action_type == 'report' else {'proposed_action': {'plan_id': plan_id, 'name': action.action_type, 'arguments': dict(action.params)}}
            if action.action_type == 'decision':
                from pearl.runtime.initial_plan import review_subject
                decision = review_subject(self, action)
                if decision is None or decision['event_id'] != action.params.get('decision_ref'):
                    raise ValueError('Review the current canonical scientific decision')
                proposal = {'proposed_decision': deepcopy(decision), 'decision_subject_id': decision['event_id'], 'review_target': design_review_target(decision['event_id'])}
                if 'initial_proposal_ref' in decision:
                    proposal.update(working_plan=decision['proposed_plan']['plan'], proposed_plan=deepcopy(decision['proposed_plan']), initial_proposal_ref=decision['initial_proposal_ref'])
            if action.action_type == 'report' and self.world.domain == 'enzyme':
                proposal['adopted_analysis_intervals'] = adoption_intervals(action.params.get('calculation_ids', []), self.board.event_log, self._evidence)
            if action.action_type == 'report':
                proposal['review_target'] = report_review_target(action.params, plan_id)
                proposal['report_revision'] = deepcopy(self._report_revision)
                proposal['report_computations'] = computation_context(self.board.event_log)
            if action.action_type in ('transfer', 'mix'):
                subject = self._action_decision_subject(action)
                if subject is not None:
                    proposal['decision_subject_id'] = subject
                proposal['action_preparations'] = preparation_focus(action, self.world.inventory, preparation_summary(self.board.event_log, self.world.briefing()['reagents']))
            if action.action_type == 'report' and 'task_resolution' in action.params:
                proposal['proposed_report']['task_resolution'] = dict(action.params['task_resolution'])
            proposal['review_workflow'] = {'phase': 'correction' if invalid is not None else 'decision' if attempt >= 3 else 'evidence_gathering', 'instruction': 'In the decision or correction phase, submit your review using the public evidence already available. State concern or uncertainty where evidence is insufficient; this phase does not imply support or action approval. Correct validation errors without inventing evidence.'}
            try:
                name, p = self._call('predictor', **proposal)
            except ToolResponseValidationError as exc:
                if invalid is not None:
                    raise invalid from exc
                raise
            if name != 'submit_review':
                try:
                    self.last_result = self._utility('predictor', name, p)
                except (ValueError, KeyError, TypeError) as exc:
                    if invalid is not None:
                        raise invalid from exc
                    raise
                continue
            try:
                return self._submit_review(action, plan_id, p)
            except (ValueError, KeyError, TypeError) as exc:
                failures += 1
                feedback = {'status': 'invalid_scientific_review', 'validation_status': 'invalid', 'plan_id': plan_id, 'review_scope': action.action_type, 'message': str(exc), 'submitted_review': deepcopy(p), 'effect': 'Unvalidated feedback only; no predictions, exclusions or action approval were applied. Correct the identified fields using public evidence. One submit-only correction is allowed; concern and uncertainty remain valid judgments.'}
                if isinstance(exc, SupportingInputError):
                    feedback['supporting_input_diagnostics'] = deepcopy(exc.details)
                event = ObservationEvent(source_agent='predictor', observation_type='scientific_review_validation_error', payload=deepcopy(feedback))
                self.board.publish(event)
                feedback['event_id'] = event.event_id
                self.last_result = feedback
                invalid = ReviewValidationError(str(exc), feedback)
                if failures >= 2:
                    raise invalid from exc
        if invalid is not None:
            raise invalid
        raise RuntimeError('Predictor did not submit a review within its bounded consultation turns')

    def _delivered_evidence(self, role):
        if self.continuous_camera and role in self.continuous_camera.snapshot_evidence:
            observed = self.continuous_camera.snapshot_evidence[role]
            return {mid: self._evidence[mid] for mid in observed}
        return self._evidence

    def _submit_review(self, action, plan_id, p):
        review_evidence = self._delivered_evidence('predictor')
        if p.get('verdict') not in ('supported', 'concern', 'uncertain') or not isinstance(p.get('rationale'), str) or (not p['rationale'].strip()):
            raise ValueError('Predictor must provide a verdict and rationale')
        import math
        expectations = p.get('expectations', [])
        if action.action_type in ('report', 'decision') and expectations:
            raise ValueError('Scientific decision or report review cannot register future camera predictions')
        if not isinstance(expectations, list):
            raise ValueError('Expectations must be a list')
        for e in expectations:
            if not isinstance(e, dict) or e.get('location') not in self.world.inventory or e.get('field') not in ('od_estimate', 'captured_at_s', 'rgb_0', 'rgb_1', 'rgb_2'):
                raise ValueError('Expectation requires a declared location and camera field')
            if not all((isinstance(e.get(k), (int, float)) and (not isinstance(e[k], bool)) and math.isfinite(e[k]) for k in ('lower', 'upper'))) or e['lower'] > e['upper']:
                raise ValueError('Expectation requires ordered finite bounds')
        if self.world.domain == 'enzyme' and 'analysis_exclusions' not in p:
            raise ValueError('Enzyme reviews require explicit analysis_exclusions; use [] when none apply')
        references, binding = bind_references(p.get('observation_references'), review_evidence, p.get('rationale'), known_evidence=self._evidence)
        observations = resolve_references(references, review_evidence, p.get('rationale'))
        analysis_proposals = validate_proposals(p.get('analysis_exclusions', []), review_evidence)
        expected_volumes = validate_volumes(action, p.get('expected_volumes'), self.world.inventory)
        decision_subject = action.params.get('decision_ref') or plan_id if action.action_type in ('report', 'decision') else self._action_decision_subject(action)
        if action.action_type == 'decision':
            from pearl.runtime.initial_plan import review_subject
            current = review_subject(self, action)
            if current is None or current['event_id'] != decision_subject:
                raise ValueError('Review the current canonical scientific decision')
        decision_assessment = validate_assessment(p.get('decision_assessment'), decision_subject, review_evidence, proposed_report=action.params if action.action_type == 'report' else None, public_setup=self.world.briefing()) if decision_subject is not None else None
        task_assessment = read_resolution(p) if action.action_type == 'report' else None
        task_disagreement = task_assessment is not None and task_assessment['status'] != 'unassessed' and (action.params.get('task_resolution', {}).get('status', 'unassessed') not in ('unassessed', task_assessment['status']))
        intervals = []
        assessments = []
        basis_disagreement = False
        if self.world.domain == 'enzyme':
            if action.action_type == 'report':
                intervals = adoption_intervals(action.params.get('calculation_ids', []), self.board.event_log, review_evidence)
            assessments = validate_basis(p.get('analysis_basis'), intervals, required=p['verdict'] == 'supported')
            if action.action_type == 'report' and assessments:
                basis_disagreement = basis_choices(assessments) != basis_choices(action.params.get('analysis_basis', []))
        verdict = aggregate_advice(p['verdict'], decision_assessment['verdict'] if decision_assessment else 'supported', task_disagreement or basis_disagreement)
        event = PredictionEvent(source_agent='predictor', plan_id=plan_id, predicted_outcomes=expectations, match_status=verdict, is_uncertain=verdict == 'uncertain')
        self.board.publish(event)
        review = {**event.to_dict(), 'rationale': p['rationale'], 'observation_references': references, 'authored_observation_references': deepcopy(p['observation_references']), 'citation_binding': binding, 'referenced_observations': observations, 'expected_volumes': expected_volumes}
        if decision_assessment is not None:
            review['decision_assessment'] = decision_assessment
        if action.action_type == 'decision':
            review.update(review_scope='decision', decision_ref=decision_subject, review_target=design_review_target(decision_subject))
            if action.params.get('proposal_ref') is not None:
                review['initial_proposal_ref'] = action.params['proposal_ref']
        if self.continuous_camera:
            review['reviewed_input_snapshot'] = deepcopy(self.continuous_camera.last_snapshot.get('predictor'))
        if self.world.domain == 'enzyme':
            review.update(analysis_basis=assessments, adopted_analysis_intervals=intervals, analysis_basis_disagreement=basis_disagreement)
        if task_assessment is not None:
            review.update(review_target=report_review_target(action.params, plan_id), task_resolution=task_assessment, report_support=p['verdict'], decision_assessment=decision_assessment, report_id=plan_id, decision_ref=action.params.get('decision_ref'), task_status_disagreement=task_disagreement)
        self.board.publish(ObservationEvent(source_agent='predictor', observation_type='scientific_review', payload=deepcopy(review)))
        publish_proposals(self.board, analysis_proposals, event.event_id)
        self.last_result = deepcopy(review)
        return review

    def _validate_dispatch(self, action):
        self.world.validate_action(action)
        if self.continuous_camera and action.action_type == 'transfer' and (action.params.get('mix_after_transfer_ul') is not None):
            import math
            amount = action.params['mix_after_transfer_ul']
            available = self.world.inventory[action.params['target']] + action.params['volume_ul']
            if isinstance(amount, bool) or not isinstance(amount, (int, float)) or (not math.isfinite(amount)) or (not 1 <= amount <= min(300, available)):
                raise ValueError('Requested followup mix exceeds post-transfer nominal volume')

    def _dispatch(self, action, plan_id):
        if self.continuous_camera and action.action_type == 'transfer' and (action.params.get('mix_after_transfer_ul') is not None):
            self._validate_dispatch(action)
            amount = action.params['mix_after_transfer_ul']
            params = {k: v for k, v in action.params.items() if k != 'mix_after_transfer_ul'}
            first = ActionSpec(action_id=action.action_id, action_type='transfer', params=params)
            self._dispatch(first, plan_id)
            self._dispatch(ActionSpec(action_id=uuid.uuid4().hex, action_type='mix', params={'location': params['target'], 'volume_ul': amount}), plan_id)
            return
        if self.continuous_camera and self.pending and (action.action_type in ('transfer', 'mix')):
            raise PendingReviewError('Resolve pending observations before executing a liquid action', self.pending, self.board.event_log)
        self._validate_dispatch(action)
        volume_balance = nominal_transfer_balance(action.params, self.world.inventory) if action.action_type == 'transfer' else None
        self.board.publish(ToolCallEvent(source_agent='actor', tool_name=action.action_type, params=dict(action.params), result={'status': 'dispatching'}, plan_id=plan_id, tool_call_id=action.action_id, executed=None))
        if action.action_type == 'inspect' and (not self.continuous_camera):
            self._start_capture(action.params['locations'])
        results = self.actor.execute(ProceedSignal(plan_id=plan_id, actions=(action,)))
        if self.continuous_camera and results and results[0].ok:
            through = results[0].observation.get("completed_at_s", self.world.time_s)
            self.continuous_camera.drain(through_s=through)
        if len(results) != 1 or not results[0].ok:
            raise RuntimeError('Actor execution failed')
        result = results[0]
        observation = deepcopy(result.observation)
        if volume_balance is not None:
            observation['nominal_volume_balance'] = volume_balance
        if action.action_type in ('transfer', 'mix'):
            self._has_liquid_actions = True
        self.board.publish(ToolCallEvent(source_agent='actor', tool_name=action.action_type, params=dict(action.params), result={'ok': result.ok, 'observation': observation}, plan_id=plan_id, executed=True, tool_call_id=action.action_id))
        self.last_result = observation
        if action.action_type == 'inspect' and self.continuous_camera:
            pass
        elif action.action_type == 'inspect':
            packet = result.observation
            self._evidence.update({m['measurement_id']: m for m in packet['measurements']})
            self.board.publish(ObservationEvent(source_agent='actor', observation_type='camera', payload=packet))
            self._collect_findings()
        elif self.continuous_camera is not None:
            pass
        elif self.world.domain == 'color':
            self._capture_after_action([p for p in self.world.inventory if p.startswith('plate:')])
        else:
            occupied = [p for p, v in self.world.inventory.items() if p.startswith('plate:') and v > 0]
            if occupied:
                self._capture_after_action(occupied)

    def _capture_after_action(self, locations):
        return self._capture(locations)

    def _respond(self, p):
        decision = p['decision']
        evidence = p.get('evidence_ids', [])
        if decision not in ('accept', 'reject', 'revise', 'proceed', 'acknowledge') or not isinstance(p.get('rationale'), str) or (not p['rationale'].strip()):
            raise ValueError('Provide a disposition and rationale')
        if not isinstance(evidence, list) or any((not isinstance(i, str) or i not in self._evidence for i in evidence)):
            raise ValueError('Evidence IDs must identify actual acquired measurements')
        if not isinstance(p['review_id'], str):
            raise ValueError('Provide an exact review ID string')
        review = next((r for r in self.pending if r['event_id'] == p['review_id']), None)
        if review is None:
            raise PendingReviewError('No such pending review', self.pending, self.board.event_log)
        if decision == 'proceed' and self._action is not None:
            current = current_decision(self.board.event_log)
            if (current['event_id'] if current else None) != self._action_decision_ref:
                raise ValueError('Scientific decision changed after action review; withdraw the pending action with revise, accept or reject, then propose it for review under the current decision')
        from pearl.runtime.review_memory import report_decision_subject
        logical_report_rejection = decision == 'reject' and self._action is None and (report_decision_subject(review, self.board.event_log) is not None)
        if (decision in ('reject', 'proceed', 'acknowledge') or review.get('validation_status') == 'invalid') and (not evidence) and (not logical_report_rejection):
            raise ValueError('Proceeding after a scientific review requires observed evidence')
        self.board.publish(PeerReviewDispositionEvent(source_agent=self.planning_role, plan_id=review.get('plan_id', ''), review_event_id=review['event_id'], decision=decision, rationale=p['rationale'], evidence_ids=evidence))
        self._handled.add(review['event_id'])
        self.pending.remove(review)
        self.last_result = {'status': 'recorded', 'decision': decision, 'pending_action_status': 'none' if self._action is None else 'held' if decision == 'acknowledge' else 'authorized' if decision == 'proceed' else 'withdrawn', 'meaning': 'Only proceed authorizes an action; accept/revise/reject withdraw it. acknowledge retains the queue without execution; manage_pending_action provides explicit subsequent authorization or withdrawal.'}
        if decision == 'acknowledge':
            return
        if decision != 'proceed':
            self._action = None
        if not self.pending and self._action:
            action, plan_id = self._action
            self._action = None
            self._dispatch(action, plan_id)

    def _manage_pending_action(self, p):
        if set(p) != {'action_id', 'decision', 'rationale', 'evidence_ids'} or p['decision'] not in ('proceed', 'withdraw') or (not isinstance(p['rationale'], str)) or (not p['rationale'].strip()):
            raise ValueError('Provide an action ID, proceed or withdraw, rationale and evidence IDs')
        if self._action is None or p['action_id'] != self._action[0].action_id:
            raise ValueError('Choose the exact current pending action ID')
        evidence = p['evidence_ids']
        if not isinstance(evidence, list) or any((not isinstance(mid, str) or mid not in self._evidence for mid in evidence)):
            raise ValueError('Evidence IDs must identify actual acquired measurements')
        action, plan_id = self._action
        if p['decision'] == 'proceed':
            if not evidence or self.pending:
                raise ValueError('Proceed requires acquired evidence and disposition of all pending reviews')
            current = current_decision(self.board.event_log)
            if (current['event_id'] if current else None) != self._action_decision_ref:
                raise ValueError('Scientific decision changed; withdraw and submit a new proposal')
            if self._action_review is None or self._action_review.get('plan_id') != plan_id or action.action_type not in ('transfer', 'mix'):
                raise ValueError('Pending operation requires its validated Predictor review')
            validate_volumes(action, self._action_review.get('expected_volumes'), self.world.inventory)
            self._validate_dispatch(action)
        self.board.publish(ObservationEvent(source_agent=self.planning_role, observation_type='pending_action_disposition', payload={**deepcopy(p), 'plan_id': plan_id, 'decision_ref': self._action_decision_ref}))
        self._action = None
        self._action_review = None
        self.last_result = {'status': 'recorded', 'decision': p['decision'], 'pending_action_status': 'authorized' if p['decision'] == 'proceed' else 'withdrawn'}
        if p['decision'] == 'proceed':
            self._dispatch(action, plan_id)

    def _before_finalize_report(self, report):
        """Composition hook after report validation and before any finalization."""

    def _before_publish_report(self, report):
        """Composition hook immediately before publishing the validated final report."""

    def _initialize_observations(self):
        self._capture(list(self.world.briefing()['reagents']))
        if self.world.domain == 'color':
            self._capture([p for p in self.world.inventory if p.startswith('plate:')])

    def run(self, *, max_turns=120):
        if not isinstance(max_turns, int) or isinstance(max_turns, bool) or max_turns <= 0:
            raise ValueError('max_turns must be positive')
        self._initialize_observations()
        for _ in range(max_turns):
            self.turns += 1
            name, p = (None, None)
            try:
                name, p = self._call(self.planning_role)
                initial_adoption = None
                if name == 'adopt_reviewed_plan':
                    from pearl.runtime.initial_plan import prepare_adoption
                    p, initial_adoption = prepare_adoption(self, p)
                    name = 'record_plan'
                if name == 'finish':
                    if not isinstance(p.get('conclusion'), str) or not p['conclusion'].strip():
                        raise ValueError('A conclusion is required')
                    ids = p.get('measurement_ids', [])
                    if not isinstance(ids, list) or any((not isinstance(i, str) or i not in self._evidence for i in ids)):
                        raise ValueError('Unknown measurement IDs')
                    if any((r.get('validation_status') == 'invalid' for r in self.pending)):
                        raise PendingReviewError('Respond to the pending unvalidated scientific review with rationale and acquired evidence before finalizing. No automatic exclusion has been applied.', self.pending, self.board.event_log)
                    if any((r.get('report_id') and r.get('match_status') in ('concern', 'uncertain') for r in self.pending)):
                        raise PendingReviewError('Dispose the pending scientific report assessment before finalizing. Unchanged reaffirmation needs no repeat review; changed decisions or evidence do.', self.pending, self.board.event_log)
                    if self.continuous_camera and self.pending:
                        raise PendingReviewError('Resolve pending observations before finalizing the historical report', self.pending, self.board.event_log)
                    validate_adoption(p.get('calculation_ids', []), self.board.event_log)
                    if self.world.domain == 'enzyme':
                        intervals = adoption_intervals(p.get('calculation_ids', []), self.board.event_log, self._evidence)
                        p = {**p, 'analysis_basis': validate_basis(p.get('analysis_basis'), intervals)}
                    if 'task_resolution' in p and p['task_resolution'] is None:
                        raise ValueError('Invalid scientific decision: task_resolution cannot be null')
                    resolution, decision_record, decision_ref = prepare_decision(p.get('task_resolution'), self.board.event_log, self._evidence, final=True)
                    p = {**p, 'task_resolution': resolution}
                    direct_adoption = {'direct_measurement_ids': p.get('adopted_measurement_ids', [])} if self.world.domain == 'color' else {}
                    explicit_color_selection = self.world.domain == 'color' and 'adopted_measurement_ids' in p
                    if explicit_color_selection and (not isinstance(p['adopted_measurement_ids'], list)):
                        raise ValueError('Color adopted_measurement_ids must be an acquired ID list')
                    if cohort_memory(self.board.event_log) or explicit_color_selection:
                        check = validate_cohort_adoption if p['task_resolution']['status'] == 'achieved' else adoption_coverage
                        p = {**p, 'cohort_adoption_coverage': check(p.get('calculation_ids', []), self.board.event_log, self._evidence, **direct_adoption)}
                    decision_ref = publish_decision(self.board, decision_record, decision_ref, source_agent=self.planning_role)
                    if decision_ref:
                        p['decision_ref'] = decision_ref
                    self._action = None
                    self._before_finalize_report(p)
                    if self.independent_prediction and (self._has_liquid_actions or self.review_reports_before_liquid) and self._needs_report_review(p):
                        from pearl.runtime.report_review import report_changes, report_frontier, report_subject
                        subject = report_subject(p)
                        self._report_revision = report_changes(self._last_report_subject, subject, self._last_report_id)
                        self._report_revision['new_evidence_since_review'] = bool(self._last_report_id and report_frontier(self.board.event_log) != self._last_report_frontier)
                        proposed_report = ObservationEvent(source_agent=self.planning_role, observation_type='proposed_report', payload=deepcopy(p))
                        self.board.publish(proposed_report)
                        self._report_reviewed = True
                        self._last_report_subject = subject
                        self._last_report_id = proposed_report.event_id
                        try:
                            review = self._review(ActionSpec(action_id=uuid.uuid4().hex, action_type='report', params=p), proposed_report.event_id)
                        except (ValueError, KeyError, TypeError) as exc:
                            invalid_feedback = exc.feedback if isinstance(exc, ReviewValidationError) else {}
                            if invalid_feedback:
                                self.pending.append({**deepcopy(invalid_feedback), 'match_status': 'concern', 'rationale': 'Review validation failed; consider the retained unvalidated submission and explicitly dispose it with public evidence.'})
                            self.last_result = {**deepcopy(invalid_feedback), 'status': 'invalid_report_review', 'message': str(exc), 'effect': 'No action executed. Unchanged report and evidence are not rechecked. Dispose any unvalidated review with acquired evidence and rationale; invalid exclusions are not applied. Changed claims, decisions or evidence receive review.'}
                            if isinstance(exc, SupportingInputError):
                                self.last_result['supporting_input_diagnostics'] = deepcopy(exc.details)
                            self.board.publish(ObservationEvent(source_agent='predictor', observation_type='report_review_error', payload=deepcopy(self.last_result)))
                            continue
                        finally:
                            self._last_report_frontier = self._review_frontier()
                        if review['match_status'] != 'supported':
                            self.pending.append(review)
                            self.last_result = {**review, 'effect': 'Scientific report advice only; no action executed. Revise or reaffirm with grounds. Reuse the exact reviewed report to avoid repetition; changed claims, decisions or evidence receive review.'}
                            continue
                    if self.continuous_camera and self.pending:
                        raise PendingReviewError('Resolve pending observations before finalizing the historical report', self.pending, self.board.event_log)
                    validate_adoption(p.get('calculation_ids', []), self.board.event_log)
                    if self.world.domain == 'enzyme':
                        validate_basis(p.get('analysis_basis'), adoption_intervals(p.get('calculation_ids', []), self.board.event_log, self._evidence))
                    if p['task_resolution']['status'] == 'achieved':
                        validate_cohort_adoption(p.get('calculation_ids', []), self.board.event_log, self._evidence, **direct_adoption)
                    self._before_publish_report(p)
                    self.board.publish(ObservationEvent(source_agent=self.planning_role, observation_type='final_report', payload=deepcopy(p)))
                    return self.summary('completed', report=p, task_status=p['task_resolution']['status'])
                if name == 'record_decision':
                    if set(p) != {'decision'} or not isinstance(p['decision'], dict) or set(p['decision']) != {'decision_ref', 'updates'}:
                        raise ValueError('record_decision requires decision_ref and updates inside decision')
                    _, record, reference = prepare_decision(p['decision'], self.board.event_log, self._evidence)
                    reference = publish_decision(self.board, record, reference, source_agent=self.planning_role)
                    self.last_result = {'status': 'recorded', 'decision_ref': reference, 'executed': False, 'effect': 'decision_only'}
                elif name == 'record_plan':
                    if not isinstance(p.get('plan'), str):
                        raise ValueError('Plan must be text')
                    references, binding = bind_references(p.get('observation_references'), self._delivered_evidence(self.planning_role), p['plan'], known_evidence=self._evidence)
                    observations = resolve_references(references, self._delivered_evidence(self.planning_role), p['plan'])
                    comparison = validate_timing(p.get('comparison_timing'))
                    locations = validate_locations(p.get('acquisition_locations', []), self.world.inventory)
                    cohorts = validate_updates(p.get('cohort_updates', []), self.board.event_log, self._evidence, self.world.inventory)
                    comparison_result = timing_context(comparison, acquisition_context(observations, self.board.event_log, self.world.briefing()['reagents'])) if comparison is not None else None
                    if locations and comparison is not None:
                        acquisition_schedule(locations, comparison, self.board.event_log, self._evidence, self.world.briefing(), self.world.time_s)
                    decision_ref = None
                    record = reference = None
                    if 'decision' in p:
                        _, record, reference = prepare_decision(p['decision'], self.board.event_log, self._evidence)
                    from pearl.runtime.initial_plan import enabled, stage, publish_adoption, adopted_design_exists
                    if enabled(self) and (not adopted_design_exists(self)) and (initial_adoption is None):
                        stage(self, p, record)
                        continue
                    if 'decision' in p:
                        decision_ref = publish_decision(self.board, record, reference, source_agent=self.planning_role)
                    self.comparison_timing = comparison
                    self.acquisition_locations = locations
                    self.working_plan = p['plan']
                    self.working_plan_observations = observations
                    self.board.publish(WorkingPlanDeclaredEvent(source_agent=self.planning_role, working_plan={'description': p['plan'], **({'decision_ref': decision_ref} if decision_ref else {}), **({'cohort_updates': cohorts} if cohorts else {}), **({'acquisition_locations': locations} if locations else {}), **({'comparison_timing': deepcopy(comparison)} if comparison is not None else {}), 'observation_references': references, 'authored_observation_references': deepcopy(p['observation_references']), 'citation_binding': binding, 'referenced_observations': deepcopy(observations)}))
                    if initial_adoption is not None:
                        publish_adoption(self, initial_adoption, decision_ref)
                    self._collect_findings()
                    self.last_result = {'status': 'recorded', **({'working_plan_timing': comparison_result} if comparison_result is not None else {}), 'executed': False, 'effect': 'initial_design_adopted' if initial_adoption is not None else 'notes_only', **({'decision_ref': decision_ref} if decision_ref else {}), 'action_workflow': self._action_workflow(), 'meaning': 'Only planning notes changed. Propose an actual operation with its action tool when ready; recording a plan does not request execution.'}
                elif name == 'respond_to_review':
                    self._respond(p)
                elif name == 'manage_pending_action':
                    self._manage_pending_action(p)
                elif name in ('transfer', 'mix', 'wait', 'inspect'):
                    params = dict(p)
                    expected_volumes = params.pop('expected_volumes', None) if name in ('transfer', 'mix') else None
                    action = ActionSpec(action_id=uuid.uuid4().hex, action_type=name, params=params)
                    self.world.validate_action(action)
                    if name in ('transfer', 'mix'):
                        if self._action is not None:
                            raise ValueError('Explicitly proceed with or withdraw the held action before another proposal')
                        expected_volumes = validate_volumes(action, expected_volumes, self.world.inventory)
                        if self.pending:
                            raise PendingReviewError('Respond to pending scientific reviews before another liquid action', self.pending, self.board.event_log)
                        self._require_prospective_design(action)
                        subject = self._action_decision_subject(action)
                        if self.independent_prediction and subject is not None:
                            scientific = self._review(ActionSpec(action_type='decision', params={'decision_ref': subject}), subject)
                            if scientific['match_status'] != 'supported':
                                self.pending.append(scientific)
                            if self.pending:
                                self.last_result = {'status': 'scientific_review_pending', 'executed': False, 'review_id': scientific['event_id'], 'meaning': 'Respond to the scientific advice, then submit an operation for its own review. No operation is queued or authorized.'}
                                continue
                        plan_id = uuid.uuid4().hex
                        self.board.publish(PlanEvent(source_agent=self.planning_role, plan_id=plan_id, steps=[{'action_type': name, 'params': params, 'expected_volumes': expected_volumes}], rationale=self.working_plan))
                        if not self.independent_prediction:
                            self._dispatch(action, plan_id)
                            continue
                        review = self._review(action, plan_id)
                        if review['match_status'] != 'supported' or (self.continuous_camera and self.pending):
                            self.pending.append(review)
                            self._action = (action, plan_id)
                            self._action_review = deepcopy(review)
                            current = current_decision(self.board.event_log)
                            self._action_decision_ref = current['event_id'] if current else None
                        else:
                            self._dispatch(action, plan_id)
                    else:
                        self._dispatch(action, uuid.uuid4().hex)
                else:
                    self.last_result = self._utility(self.planning_role, name, p)
            except (ValueError, KeyError, TypeError) as exc:
                self.last_result = {'status': 'invalid_input', 'message': str(exc)}
                if isinstance(exc, ContextSectionUnavailable):
                    self.last_result['context_details'] = deepcopy(exc.details)
                if isinstance(exc, SupportingInputError):
                    self.last_result['supporting_input_diagnostics'] = deepcopy(exc.details)
                diagnostics = acquired_reference_diagnostics(name, p, self._evidence, (event.event_id for event in self.board.event_log))
                if diagnostics is not None:
                    self.last_result['reference_diagnostics'] = diagnostics
                authorization = getattr(exc, 'execution_authorization', None)
                if authorization is not None:
                    self.last_result['execution_authorization'] = deepcopy(authorization)
                if isinstance(exc, PendingReviewError):
                    self.last_result['pending_review_disposition'] = deepcopy(exc.feedback)
                if isinstance(exc, ReviewConcernSelectionError):
                    self.last_result['review_concern_resolution'] = deepcopy(exc.feedback)
                if isinstance(exc, DecisionValidationError):
                    self.last_result['decision_repair'] = {**deepcopy(exc.repair), 'argument_path': 'task_resolution' if name == 'finish' else 'decision'}
                    self.board.publish(ObservationEvent(source_agent=self.planning_role, observation_type=REJECTION_TYPE, payload={'current_decision_ref': exc.repair['current_decision_ref'], 'validation_error': validation_cause(exc), 'argument_path': self.last_result['decision_repair']['argument_path'], 'rejected_submission': deepcopy(exc.repair['rejected_submission'])}))
        return self.summary('turn_limit')

    def summary(self, termination, **extra):
        return {'termination': termination, 'evaluation_status': 'not_evaluated', 'turns': self.turns, 'pending_reviews': deepcopy(self.pending), 'time_s': self.world.time_s, 'measurements': len(self._evidence), 'commands': len(self.world.command_log), **extra}
