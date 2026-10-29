# Chronicle evaluation assets

- `ablation-configurations.json` defines the four approved FF180 configurations and shared experimental controls.
- `runs/` is reserved for frozen, labelled prediction files per held-out split. Do not check private or license-restricted data into Git.
- `results/` is reserved for metrics generated from those labelled files.
- Do not commit synthetic placeholders as benchmark measurements.
- The app does not yet expose strict runtime switches for all four arms; the manifest records this explicitly. Any reported A–D comparison must document the exact implementation used for each arm and use identical model, budgets and held-out records.
