# Data guide

Only source inputs and scoring decisions are supplied. `python run_all.py` rebuilds the analytical dataset and CSV tables; they are not separate maintained copies.

## Inputs

| File | Contents |
| --- | --- |
| `inputs/model_outputs.zip` | All 1,076 final saved model-response files, unchanged. These are the retained text/JSON files after any historical syntax repairs, not complete chat logs. |
| `inputs/reviewer_workbooks.zip` | Four returned reviewer workbooks, including timing sheets. Worksheet contents are unchanged. |
| `inputs/original_records.json` | The 6,081 original records as presented in reviewer workbooks, linked to the returned workbook, sheet and row. Corrected values are read directly from those workbooks. |
| `inputs/timing.csv` | The 384 session assignments, visibility conditions, review order and active seconds, with source cells. Times are checked against the workbooks. |
| `inputs/rationale_links.csv` | Links assessment IDs to report, model and RoB item for analysis. Model identities are kept outside the adjudication records. |
| `inputs/metadata_reference_standard.xlsx` | Study-specific requested outcomes, variants and arm exclusions, with the original codebook. |
| `sources.csv` | Titles, DOI links and PDF hashes for the 100 source documents associated with the 96 reports. `source_id` maps source identifiers used in adjudication records. This inventory does not establish which PDFs were attached in every historical chat. |

Raw response files and presented records are retained separately because spreadsheet parsing sometimes changed their representation. Archive timestamps do not establish model-generation dates. Saved local-folder paths were removed from Excel metadata; worksheet contents and formatting are unchanged.

## Reference and scoring

`reference/reference_standard.json` contains the adjudicated values and source locations. `field_status.json` identifies scorable fields and accepted alternatives; `row_representation_alternatives.json` defines coherent alternative rows. `study_decisions.json` contains the row-matching rules and their explanations.

`rules/` contains eligibility exclusions, explicit row mappings, time-point equivalence and text-bound rationale decisions. MM adjudicated against the source PDFs, blinded to model and reviewer identities. The 1,152 rationale assessments retain their decisions, supporting evidence and text hashes under assessment IDs, without model or reviewer identities. `inputs/rationale_links.csv` provides the separate linkage used by the analysis.

`manifest.json` contains source-file hashes and the expected hashes of 14 reconstructed data files. Rebuilding must reproduce those files exactly; compressed files are compared after decompression.

## Key variables

- `study_id` identifies a report. Known companion reports are grouped in a sensitivity analysis.
- `model`: `gpt` or `claude`; `task`: `data` or `rob`.
- `assigned_reviewer`: R1 (MK) or R2 (BJ); `reviewer` records the actual reviewer.
- `original_error` and `reviewed_error`: 0 for correct, 1 for incorrect, null when unscored. E1 denotes omission/completeness errors; E2 denotes incorrect or unsupported output.
- `primary_eligible` selects the main-report analysis; `augmented_eligible` also admits eligible supplement-only fields.
- Category C fields are unverifiable and excluded from binary accuracy. A missing value is not zero.

The main extraction analysis includes 24,899 eligible fields per model. Randomization uses seeds 20260625 and 20260626; bootstrap analyses use 10,000 resamples and seed 20261007.
