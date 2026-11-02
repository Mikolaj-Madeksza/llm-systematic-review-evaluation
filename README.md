# LLM systematic review evaluation

Materials and code for the evaluation of data extraction, risk-of-bias assessment and human verification across 96 reports and 384 review sessions.

## Contents

- `01_protocol/`: the supplied protocol, data-extraction prompt, RoB prompt and additional instructions, unchanged.
- `02_data/`: original responses, reviewer workbooks, source references and scoring decisions. See the [data guide](02_data/README.md).
- `03_analysis/`: data reconstruction, randomization, statistical analyses and figures. The [analysis plan](03_analysis/ANALYSIS_PLAN.md) records the implemented methods and reporting limitations.

## Reproduce

Use Python 3.14 and R 4.5.2. Install Arial and Poppler (`pdffonts`); on macOS use `brew install poppler`. Linux PDF export requires Cairo-enabled R.

```sh
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
Rscript setup.R
python run_all.py
```

R packages are restored from `renv.lock`. Source installation of graphics packages may require FreeType, HarfBuzz, FriBidi, PNG, JPEG and TIFF libraries.

The runner rebuilds the data, verifies its hashes, reproduces the recorded reviewer assignments, and runs all analyses. Tables and figures appear in `03_analysis/results/current/`. Generated data and results are excluded from the shared bundle to avoid duplication.

The protocol describes the planned workflow; the analysis plan documents later operational decisions. The protocol records GPT-5.5 (High) and Claude Opus 4.7 (High). Exact generation dates, backend versions, complete chat histories and resolved prompt-error rerun counts are unavailable, so this package reproduces analyses of saved responses rather than exact LLM generations.

## License

Original code is provided under the [MIT License](LICENSE). Third-party articles and ROBUST-RCT content retain their own terms. The [ROBUST-RCT manual and instrument](https://doi.org/10.1136/bmj-2024-081199) are available from the publisher; source-publication links are in `02_data/sources.csv`.
