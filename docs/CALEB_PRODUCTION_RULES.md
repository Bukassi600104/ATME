# Caleb research: executable production rules

Date: 2026-09-06. Phase 1 working contract under the approved research-first plan.

These rules describe functional production behavior observed in the supplied packets. They do not claim access to the creator's project files. Timings for new original examples are authored test timings, not measurements copied from the research.

## Evidence sources

- HBF: `high-bandwidth-flash-forensic-addendum.zip`, video `ZxBRtRjMU88`, corrected events/activations/visibility and observations AOBS01-AOBS07.
- Harness: `agent-harness-full-forensic-pass.zip`, video `1a1VXDdIyrk`, observations OBS01-OBS10 and EC01-EC06.
- Jalapeno: `openai-jalapeno-full-forensic-pass.zip`, video `yHNp_rT6uEo`, observations OBS01-OBS07 and EC01-EC06. Complete sampled visual coverage; continuous audiovisual coverage not certified.

Original ZIPs stay outside the repository in the user's ATME DOCS folder. Preserve their checksums. These references are package-local IDs, not interchangeable IDs across videos.

## Evidence-to-implementation matrix

| ID | Observed behavior and evidence | Current limitation | Required implementation | Observable acceptance |
|---|---|---|---|---|
| R01 | A conceptual board can disappear and return. HBF AOBS04/B02; Harness OBS05/B02; Jalapeno OBS02 | All elements share one forever-growing canvas | Stable board IDs and non-overlapping activation intervals | Evidence board replaces diagram; diagram returns with existing objects intact and no evidence leftovers |
| R02 | Objects accumulate within a board. Harness OBS02; HBF AOBS05; Jalapeno OBS02 | One generated beat per scene and permanent global persistence | Multiple timed events per beat; board-scoped lifetimes | Several additions occur in one narrated beat; unrelated boards never inherit objects |
| R03 | Attention marks are temporary. Harness OBS03; Jalapeno OBS03; HBF AOBS06 | Draw completion caches objects indefinitely | Visibility intervals independent of creation time; explicit temporary marks | Mark disappears while its target remains; random seeking reproduces both states |
| R04 | Evidence excursions can return to the same or a developed abstraction. Harness EC01/EC02/EC04; Jalapeno EC01/EC04/EC06 | Rectangle/text/arrow only; no external evidence layer | Evidence asset, reading hold, optional annotation, explicit destination board/version | Evidence is readable, annotation draws attention, return resolves to designated state |
| R05 | Annotation is common, not mandatory in every evidence cycle. Harness EC03 and Jalapeno EC05 have empty annotation lists | Earlier analysis risks a rigid four-step template | Optional annotation stage with explicit omission; preserve partial cycles | A short evidence insertion can return without manufacturing an annotation |
| R06 | Hard cuts separate some rhetorical phases. Harness OBS04; Jalapeno OBS04 | Camera always interpolates toward each subsequent cue | Explicit cut versus movement transition | At a cut boundary the new view appears immediately; no pre-cut pan |
| R07 | Movement is functional and varies across videos. HBF camera counts; Harness OBS04; Jalapeno OBS04 | Fixed automatic reframe and 600 ms interpolation | Authored movement start/end and hold; no motion inferred from scene count | Hold remains fixed; pan/zoom occurs only in its declared interval |
| R08 | Attention arrows and semantic connectors have different roles. HBF AOBS06 and disclosed self-endpoint convention | Arrows lack an explicit role and meaningful anchor handling | Targeted pointer with free source anchor; relationship connector with valid endpoints | Pointer does not become a self-loop; semantic link survives board return with correct endpoints |
| R09 | Visual actions relate to narrated ideas. Harness OBS02/INT02; Jalapeno candidate test | Later elements are spread fractionally across scene duration; every directive becomes draw | Preserve action kind and explicit trigger/time with alignment-confidence metadata | Reveal does not draw slowly; replacement removes prior state; uncertain trigger is disclosed |
| R10 | Sponsor section is optional and can preserve an editorial board. Harness sponsor-analysis/B02; HBF/Jalapeno sponsor absent | No section/return model | Optional section and explicit board return; use same activation mechanism | Removing sponsor interval produces a coherent editorial variant; no mandatory sponsor in unrelated projects |
| R11 | Conclusion can resolve conceptually without reproducing opening artwork. Harness OBS09; Jalapeno OBS06 | Four coarse script phases do not express visual resolution | Narrative relationship between opening question and concluding model | Final approved board explains the opening tension; literal return is optional |
| R12 | Density and pace measurements depend on sampling and grouping | Risk of treating fixed values as defaults | Configurable authored settings, evidence provenance and uncertainty | No fixed two-second action clock or universal eleven-object cap derived from these packets |

## Corrections to aggregation

- Harness reports five complete evidence cycles across the whole video, but EC06 is sponsor content. Its editorial records contain four labelled complete cycles and one partial cycle. Do not aggregate all five as editorial cycles.
- A return-to-abstraction can land on a different developed board (Harness EC02/EC04, Jalapeno EC01/EC06). Distinguish this from restoration of the exact earlier board.
- Harness density is sampled across the full video including sponsorship. Jalapeno density averages activations, not elapsed time. Recompute compatible populations before comparing averages.
- A primary event action tally and an activation-level camera tally can differ; preserve both and reconcile before using a total. Do not silently choose the larger number.
- All studies use caption timing insufficient to establish word-exact synchronization. Runtime frame intervals are authored output instructions; research onset intervals remain observations with uncertainty.

## First original sequence: Why a queue grows

Purpose: demonstrate board memory, transient attention, evidence, and conceptual resolution using original assets. This is a short diagnostic fixture on the way to the required full video, not final acceptance.

1. Queue board: introduce arrivals and service capacity as two distinct objects; connect their relationship; add a backlog object on a later event within the same explanatory beat.
2. Add a temporary pointer to the capacity constraint. Remove only the pointer after its attention interval.
3. Cut to an original, clearly labelled illustrative measurement chart (not claimed as external research evidence). Show the chart before its focus annotation.
4. Return to the queue board. Earlier objects retain geometry; the expired pointer stays absent. Add the consequence label to the returned state.
5. Hold on the resolved model: backlog grows when arrivals exceed service. The original question is answered visually.

Fixture timings will be deliberately chosen and documented as synthetic test timings. The full-video gate requires an approved continuous recording, a complete original explanation, and human review.

## Implementation sequence and safeguards

First implement R01-R03 with small optional extensions to the existing layout input and state-aware layer caching; preserve v1 rendering for inputs without the extensions. Then R06-R07 explicit camera behavior, R04-R05 evidence composition, and R08-R09 richer actions/anchors/timing. R10 uses the same board activation mechanism. R11 is reviewed across the complete narrative. R12 applies throughout.

Validate unique IDs, existing board references, half-open non-empty visibility intervals, activation ordering, no conflicting simultaneous boards, and truthful rejection of unsupported operations. Keep old cached-layer performance on legacy layouts; bound new state caches. Preview and render must use the same state evaluation.

Architecture migrations, MCP/provider retirement and the dashboard redesign stay deferred until the complete video-quality gate in the approved plan.
