# PEARL

PEARL runs natural-language laboratory requests with an OT-2 and a camera connected to the host computer. Five independent LLM roles communicate through a typed shared blackboard:

| Role | Responsibility |
| --- | --- |
| Reasoner | Interpret the request, design the experiment, weigh evidence and make scientific decisions. |
| Predictor | Independently review designs, operations and conclusions; publish predictions and concerns. |
| Knowledge | Search general scientific references and assess their relevance, applicability and limitations. |
| Watchdog | Monitor acquired evidence and peer concerns; approve, hold or reject each exact execution request. |
| Actor | Select and execute the immutable approved action; report execution problems. |

All five roles can read the same acquired camera records. Scientific disagreements require a reasoned response. Final execution permission and physical limits remain binding. The runtime records claims and actions; independent scientific assessment happens separately.

The fixed 25-entry Knowledge corpus provides general scientific guidance on experimental design, color mixing, enzyme kinetics, calibration, measurement uncertainty and evidence interpretation. Retrieved sources include applicability conditions and limitations; the agents assess their relevance to acquired observations.

## Installation and equipment

Use Python 3.12 or newer on the computer connected to the camera and the robot network. The OT-2 HTTP API must be reachable at the supplied IP on port 31950. Configure Gen2 single-channel pipettes and matching tips. Supported pipettes are p20, p300 and p1000; the example deck uses p300 right and p20 left. The labware is a Corning 96-well 360 uL flat plate and a NEST 12-channel 15 mL reservoir. PEARL limits nominal plate loading to 300 uL per well.

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -e '.[dev]'
cp .env.example .env
```

Set `OPENAI_API_KEY` and a model identifier supported by your endpoint in `.env`. `--model` overrides `OPENAI_MODEL`; otherwise the configured default is `gpt-5.6-terra`. `OPENAI_BASE_URL` can select an OpenAI-compatible endpoint. Model requests and actual provider token usage, including each peer, are logged. Missing usage remains unknown.

Calibrate labware positions on the OT-2. Set the camera's focus, exposure and white balance for fixed lighting. Configure the actual image crop before running an experiment:

```bash
cp config/deck_crop.example.json config/deck_crop.json
```

Edit the slot rectangles to match a raw camera image. Coordinates are fractions of the image; an optional `deck_region` is cropped first, and an optional slot `well_area` crops the well grid within that slot. Plate A1 must be the top-left well in the configured view, with A1–A12 left to right and A–H top to bottom. Reservoir A1–A12 also runs left to right. The example rectangles must be adjusted to your image. Rectangles at every crop level must stay inside their parent (1e-12 numerical tolerance); the usable well grid is checked before model admission. An explicitly selected missing or malformed crop file stops startup.

## Slots and reagents

The files in `scenarios/` contain public prompts, deck slots, available plate wells, camera settings and starting reagent declarations. They do not select an experimental recipe or supply an expected answer. Match the physical deck to the selected file, or provide an operator setup with `--setup`. Each task requires confirmation with `READY` before initializing the robot session. Prepare a fresh empty plate and fresh tipracks for each task; nominal state is not carried between requests.

The supplied deck uses plate slot 2, reservoir slot 3, primary tiprack slot 1 and secondary tiprack slot 4. Starting reagent wells and volumes are printed before confirmation. Anonymous dye labels do not provide an agent-facing color-to-location key: the agent must request observations and interpret the acquired RGB/HEX values.

| Scenario | Public request / materials |
| --- | --- |
| S1 | Create a rainbow in the well-plate; declared dye stocks and water. |
| S2 | Produce purple using red and green dye solutions; the request's material restriction remains binding. |
| S3 | Make purple; declared dye stocks and water. |
| S4 | Make bright orange; declared dye stocks and water. |
| S5–S8 | Autonomously characterize the HRP-TMB assay: identify its linear working range and estimate Km and kcat from time-resolved measurements. |

S5–S8 use the same source locations and starting volumes: reservoir A1, HRP, 2000 uL; A2, TMB 5 mM, 5000 uL; A3, PBS 1x, 15000 uL. The declared HRP concentration is 0.003 uM (3 nM) in S5–S7 and 0.03 uM (30 nM) in S8. Agents use the declared stock concentrations for reaction design, dilution accounting and apparent turnover estimates. HRP molecular weight is 44 kDa. Use continuous camera observation without acid stopping and keep the assay formulation and reaction conditions consistent across comparisons.

For color experiments, prepare red, green, blue and yellow stocks at reservoir A1–A4 and water at A5, labelled Dye 1–4 and Water in the public setup. S1–S3 start with 15000 uL per source; S4 starts with 10000 uL per source. The operator prepares the following laboratory conditions; S8's prepared HRP concentration is also declared in its public setup:

| Scenario | Laboratory preparation or intervention |
| --- | --- |
| S1 | Nominal dye stocks and an empty plate. |
| S2 | Nominal dye stocks and an empty plate; the public request restricts input liquids to red and green. |
| S3 | Rotate the plate 180 degrees after the first dispensing operation while keeping camera coordinates fixed. |
| S4 | Prepare all four dye stocks at five times their nominal relative concentration; keep water unchanged. |
| S5 | Nominal HRP, TMB and PBS stocks. |
| S6 | Use a recorded seed to select one well by preparation order among the first 15 distinct reactive preparations; add 5 uL of TMB stock once. Record the physical addition time separately from the first camera observation of the affected well. |
| S7 | Delay the first reaction readout by 20 minutes once while reactions continue; allow subsequent fresh reactions to be observed normally. Coordinate camera acquisition so the delayed readout condition also applies to continuous capture. |
| S8 | Prepare HRP at 0.03 uM (30 nM), matching the public declaration in `scenarios/S8.yaml`; keep TMB and PBS as above. |

Keep intervention records separate from the agent-facing setup and model messages. Prepare fresh labware, tips and source inventories for each independent run.

An operator setup may be YAML or JSON. Start from a scenario file, change slots/reagent declarations/camera configuration, and use its path with `--setup`. Reagents require `label` and `volume_ul`; concentrations use `concentration_value` and `concentration_unit`, with an explicit molecular weight for mass-to-molar conversion. Use `residual_ul` to reserve unaspiratable stock volume. Stock declarations and acknowledged volumes are nominal, not measured composition. Optional `scenarios: {S5: {...}, S6: {...}}` overrides may replace reagent lists and adjust deck/camera settings per task.

## Camera blank calibration

Calibration is a separate program. Put the appropriate assay blank into the selected wells using the intended plate, volume, illumination and camera settings:

```bash
python calibrate_camera.py --setup scenarios/S5.yaml --camera 0 \
  --blank-wells A1,A2 --samples 5 --output calibrations/blank.json
```

The script records effective camera readback separately from requested settings. Reusable calibration requires verified manual exposure, white balance and focus; changed or unknown effective settings block calibrated reuse. Raw observations with defaults retain unknown setting status explicitly. The script saves raw captures and a JSON containing fixed blank/dark RGB, channel weights, gamma, camera/crop binding and blank samples. Existing output files are not overwritten. The default weighting is the red camera channel (`--weights 1 0 0`); choose weights for the intended readout. It does not assign named-color standards or acceptance tolerances.

The optical defaults are:

| Setting | Default |
| --- | --- |
| Blank RGB | [240, 240, 240] |
| Dark RGB | [0, 0, 0] |
| Channel weights | [1, 0, 0] (red) |
| Gamma | 1 |
| Assumed readout noise SD | 0.35 counts per channel |
| Raw image quantization | 1 count |
| Optical path | 0.28 cm at 100 uL, proportional to nominal well volume |
| Extinction coefficient | 39000 M^-1 cm^-1 |
| Assay reference wavelength | 652 nm |

For a single channel, optical density is `-gamma * log10((I - dark) / (blank - dark))`. Rate conversion uses the declared extinction coefficient and volume-scaled optical path. The readout noise assumption is propagated to conditional OD uncertainty; it does not add noise to camera measurements. Raw RGB and clipped readings are retained. A selected calibration JSON can override the optical constants and `noise_sd_counts`; use `null` for an unknown noise SD.

To supply different assay settings when recording a blank:

```bash
python calibrate_camera.py --setup scenarios/S5.yaml --camera 0 \
  --output calibrations/assay.json --epsilon "$EPSILON_M_CM" \
  --path-length-per-100ul "$PATH_LENGTH_CM_PER_100UL" --wavelength "$WAVELENGTH_NM" \
  --noise-sd-counts 0.35
```

Optical constants and readout noise are declared analysis settings. Broad-band RGB-derived OD uses the selected channel and reference scale. The saved blank JSON contains the measured blank, camera binding and effective analysis settings.

Both experiment entry points accept `--calibration PATH`. If omitted, PEARL uses the defaults above. An explicitly selected file overrides its supplied settings; omitted optical settings retain their defaults. Calibration files are selected only through this argument. An invalid path or camera/crop binding mismatch stops startup.

## Terminal chat

```bash
python quick_start.py --robot-ip 192.168.1.2 --camera 0 \
  --setup scenarios/S5.yaml --calibration calibrations/assay.json
```

Omit `--camera` to select from attached cameras. `--list-cameras` lists usable camera indices without moving the robot or calling a model. Both experiment entry points require an OT-2 IP. Robot identity, acknowledged labware/pipette setup, camera initialization, a usable frame and valid image geometry are checked before constructing the LLM client. A failed check stops startup. Device and acquisition errors stop the running session.

Omit `--setup` to enter slots, reagents and concentrations interactively. Then type a scientific request at `You>`. `/status` shows the current setup and connection, `/setup PATH` selects the next request's setup, `/help` displays commands, and `/quit` exits. Each request starts a separate confirmed physical experiment. Ctrl+C stops execution.

## Scenario execution

```bash
python test_benchmark_scenario.py --robot-ip 192.168.1.2 --camera 0 --scenarios S2
python test_benchmark_scenario.py --robot-ip 192.168.1.2 --camera 0 --scenarios S1-4
python test_benchmark_scenario.py --robot-ip 192.168.1.2 --camera 0 \
  --scenarios S5,S6,S7,S8 --setup my_setup.yaml --calibration calibrations/assay.json
```

`--scenarios all` is the default. Ranges also accept `S1-S4`, and comma-separated selections preserve order without duplicates. The script loads the corresponding scenario prompt and setup, asks for physical preparation, executes, and writes logs. Operational errors stop the batch. A normal finish is not a scientific pass; evaluation is separate. `--log-dir` selects the parent log folder, `--max-turns` sets the main planning bound, and `--camera-interval` requests capture cadence in seconds.

Actual monotonic time includes model latency, pipetting, processing and waits. Scientific observation starts only on an explicit inspection request. Thereafter a capture worker observes all configured plate wells together while models and robot operations proceed. The same wells can be followed over time; the agent chooses its layout and replication. Frames carry actual acquisition bounds and operation overlap. No earlier or missed frame is reconstructed. A model response is validated against the evidence delivered before its call. Uncertain command completion or acquisition failure stops the physical session without retrying the liquid action.

## Ablations

Select an ablation only in `test_benchmark_scenario.py`; `full` is the default.

```bash
python test_benchmark_scenario.py --robot-ip 192.168.1.2 --camera 0 \
  --scenarios S5 --ablation no_knowledge --calibration calibrations/assay.json
```

| Profile | Composition and transferred responsibilities |
| --- | --- |
| `full` | Five independent LLM roles and shared blackboard. |
| `no_reasoner` | Predictor takes planning and scientific decisions; Knowledge, Watchdog and Actor remain. |
| `no_predictor` | Reasoner owns prediction/review in addition to planning. |
| `no_knowledge` | Reasoner and Predictor take source retrieval and knowledge assessment. |
| `no_watchdog` | Reasoner and Predictor take monitoring/authorization duties; Reasoner gives final request-bound permission. |
| `base_llm` | One Actor LLM owns all scientific and execution duties; conversation context, tools and camera. |
| `pearl_minimal` | One Actor LLM owns all duties with shared blackboard context management. |

No profile removes Actor or replaces an absent scientific peer with a rule-based peer. Physical admission and execution limits apply to every profile. Population/profile identity remains in logs and independent assessments.

## Logs and independent P/A/E assessment

Each run creates its own folder under `logs/`:

- `setup.json`: original public request, nominal materials, equipment and optical declarations.
- `events.jsonl`: ordered shared-blackboard events, acquired measurements, scientific decisions, reviews, analyses and acknowledged actions.
- `model.exchanges.jsonl`: role-tagged model requests, returned text/tool selections and actual usage.
- `robot.receipts.jsonl`: requested physical commands and firmware receipts.
- `frames/`: raw image files and acquisition records.
- `result.json`: operational termination and the agent's report, with `evaluation_status: not_evaluated`.

Prepare an independent public-only review packet from a completed run:

```bash
python assess_logs.py prepare logs/S5_RUN_ID --output reviews/S5 --reviewer independent-scientist
python assess_logs.py assignment reviews/S5 > reviewer_request.json
```

Supply that request's full instruction, rubric, output contract and exact seven-file allowlist to a fresh independent reviewer. The script does not contact a reviewer or infer grades. The reviewer writes `reviews/S5/INDEPENDENT_REVIEW.json`. Bind that authored JSON without changing it:

```bash
python assess_logs.py bind reviews/S5 --review reviews/S5/INDEPENDENT_REVIEW.json --require-pass
```

The contract is `public-scientific-evidence-pae-v1`. **Planning** judges the initial effective prospective design at its information frontier. **Adaptation** links available observations/concerns to an appropriate response or justified continuation. **Execution** judges the supported achieved outcome and adopted-result lineage. Only literal P=true, A=true and E=true satisfy the progression gate. False and null remain distinct; operational failure is not evaluated. Packet identity, immutable public files, evidence references, rubric and review provenance are checked. Structural consistency does not establish scientific truth. The full rubric is in [SCIENTIFIC_EVIDENCE_CONTRACT.md](docs/evaluation/SCIENTIFIC_EVIDENCE_CONTRACT.md).

## Offline development checks

On Linux, install the system `libseccomp` library and run:

```bash
PYTHONPATH=src:. PYTHONDONTWRITEBYTECODE=1 python tests/offline.py
```

The launcher removes API credentials, disables dotenv loading, blocks network connections and guards device opens. Tests exercise device admission, action authorization, image processing, calculations and assessment records.
