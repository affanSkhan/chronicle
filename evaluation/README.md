# Chronicle evaluation assets

- `ablation-configurations.json` defines the four approved FF180 configurations and shared experimental controls.
- `runs/` is reserved for frozen, labelled prediction files per held-out split. Do not check private or license-restricted data into Git.
- `results/` is reserved for metrics generated from those labelled files.
- `pilot/` contains a committed synthetic smoke fixture and generated metrics
  solely to verify harness wiring; it is not a benchmark measurement.
- The app exposes strict runtime switches for all four arms through `evaluation_arm` on research-run creation. Any reported A–D comparison must still document the exact implementation used for each arm and use identical model, budgets and held-out records.
- `services/api/scripts/acceptance_smoke.py` provides a repeatable deployed API smoke flow. It validates liveness, database readiness, security headers, authentication, workspace lifecycle, run creation, and destructive workspace cleanup without printing credentials.
