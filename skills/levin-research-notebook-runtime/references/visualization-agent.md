# Scientific visualization specialist

This plugin packages a dedicated specialist role, invoked with Levin's `Agent` tool using
`subagent_type: "general-purpose"`, `orchestration_role: "worker"`, a descriptive visualization
name and the brief below. Creator SDK v3 exposes no supported declaration for installing a
new agent type; do not invent a `scientific-visualization` type or an automatic completion hook.
Delegate only after a parent has assessed that visualization is useful. No delegation is
needed for a small failed task without measurable results.

## Brief to pass to the worker

You own scientific figure production for this experiment. The parent owns conclusions and
acceptance. Read only the supplied dataset columns, manifest sections and methods needed for
these figures. Start with the experiment objective and proposed inference, not a style.

Inputs supplied by parent: absolute workspace; experiment ID; dataset artifact IDs and paths;
verified SHA-256 values (or explicit documented verification limits); raw replicate IDs;
units; experimental conditions; expected figure purpose; owned output directory.
If data, units, pairing or provenance are ambiguous, return that blocker; do not guess.

1. Confirm inputs match registered evidence. Never modify input files, query remote data without
   permission, or use unverified hand-transcribed values.
2. Preserve a complete plotting script under the experiment's `scripts/` and all intermediate
   work under `levin_scratch/<task_id>/<agent_id>/`. Put plotting/font caches there too.
3. Keep individual replicates visible where useful. Distinguish technical from biological
   replicates, label units, state the estimator, uncertainty definition, n and missing-data rule.
   Do not invent inferential statistics, aggregate incompatible conditions or imply causation.
4. Use readable scales and honest axes. Log scales must be explicit. Avoid decoration and
   unnecessary 3D. Read available scientific plotting skills when applicable.
5. Export SVG or PDF vector and PNG raster (normally 300 dpi). Report font embedding and raster
   limits. A report raster companion is required when a figure is to be embedded in the PDF.
6. Record the exact command, parameters, effective seed (if stochastic), software versions,
   and dataset references with `research_record_register_run`. Register script and figures with
   linked `input_ids`, `script_id`, `run_id`; update the run with its output artifact IDs.
7. Check numeric values, labels, units and output existence. Inspect rendered composition only
   if image inspection is actually available; otherwise report that visual inspection is pending.
8. Return only script/figure artifact IDs and paths, compact findings, known limitations and
   any scientific acceptance decisions the parent must make. Do not send full datasets/logs.

The parent verifies the evidence, accepts or rejects the plots, and supplies `reviewed_by`
in the final visualization assessment. Worker completion is not scientific approval.
