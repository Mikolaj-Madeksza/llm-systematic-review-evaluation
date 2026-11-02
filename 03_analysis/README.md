# Analysis

Run `python run_all.py` from the repository root. To rebuild and verify data only, run `python 03_analysis/verify_data.py --rebuild`.

The runner reconstructs reviewer records, verifies source times and randomized assignments, fits all specified analyses and creates both figures. Results are written to `03_analysis/results/current/`.

`ANALYSIS_PLAN.md` defines estimands, denominators, models and sensitivity analyses. `load_assessments.py` reads the compact source bundle; `build_dataset.py` applies the scoring rules. The remaining scripts calculate or verify the results.
