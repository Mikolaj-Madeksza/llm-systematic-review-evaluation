"""Reproduce reviewer assignments and compare them with the recorded sessions."""

import random
from pathlib import Path

import pandas as pd
from load_assessments import load_assessments

ROOT = Path(__file__).resolve().parents[1]
MODELS = ["gpt", "claude"]
REVIEWERS = ["R1", "R2"]
EXPECTED_N_STUDIES = 96
SEED = 20260625


def require_complete_counts(counts: pd.DataFrame, count_column: str) -> None:
    studies = sorted(counts["study_id"].astype(str).unique())
    if len(studies) != EXPECTED_N_STUDIES:
        raise ValueError(
            f"Expected {EXPECTED_N_STUDIES} studies, observed {len(studies)} in {count_column}"
        )
    expected_pairs = {(study, model) for study in studies for model in MODELS}
    observed_pairs = set(
        zip(counts["study_id"].astype(str), counts["source_model"].astype(str))
    )
    missing = sorted(expected_pairs - observed_pairs)
    extra = sorted(observed_pairs - expected_pairs)
    if missing or extra:
        raise ValueError(
            f"Incomplete study-model counts for {count_column}; missing={missing[:10]}, extra={extra[:10]}"
        )


def choose_balanced_model_split(
    counts: pd.DataFrame, burden_column: str, rng: random.Random
) -> set[str]:
    wide = counts.pivot(
        index="study_id", columns="source_model", values=burden_column
    ).loc[:, MODELS]
    wide = wide.sample(frac=1, random_state=rng.randrange(1000000000))
    base = int(wide["claude"].sum())
    total = int(wide.sum(axis=1).sum())
    diffs = (wide["gpt"] - wide["claude"]).astype(int).to_dict()
    states: dict[tuple[int, int], tuple[tuple[int, int], str] | None] = {(0, 0): None}
    for study_id, diff in diffs.items():
        new_states = dict(states)
        for count, total_diff in states:
            if count >= 48:
                continue
            key = (count + 1, total_diff + diff)
            if key not in new_states:
                new_states[key] = ((count, total_diff), study_id)
        states = new_states
    candidates = [
        (diff, abs(base + diff - (total - (base + diff))))
        for count, diff in states
        if count == 48
    ]
    if not candidates:
        raise RuntimeError("Could not construct a 48/48 model split")
    best_gap = min((gap for _, gap in candidates))
    best_diffs = [diff for diff, gap in candidates if gap == best_gap]
    selected_diff = rng.choice(best_diffs)
    selected: set[str] = set()
    state = (48, selected_diff)
    while state != (0, 0):
        previous, study_id = states[state]
        selected.add(study_id)
        state = previous
    return selected


def choose_visible_assignments(
    assignments: pd.DataFrame, burden_column: str, rng: random.Random
) -> set[int]:
    visible_indices: set[int] = set()
    for reviewer in REVIEWERS:
        reviewer_df = assignments.loc[assignments["assigned_reviewer"] == reviewer]
        for model in MODELS:
            model_df = reviewer_df.loc[reviewer_df["source_model"] == model]
            if len(model_df) != 48:
                raise ValueError(
                    f"Expected 48 {model} assignments for {reviewer}; observed {len(model_df)}"
                )
            model_df = model_df.sample(frac=1, random_state=rng.randrange(1000000000))
            burdens = model_df[burden_column].astype(int).to_dict()
            total = sum(burdens.values())
            states: dict[tuple[int, int], tuple[tuple[int, int], int] | None] = {
                (0, 0): None
            }
            for idx, burden in burdens.items():
                new_states = dict(states)
                for count, subtotal in states:
                    if count >= 24:
                        continue
                    key = (count + 1, subtotal + burden)
                    if key not in new_states:
                        new_states[key] = ((count, subtotal), idx)
                states = new_states
            candidates = [
                (subtotal, abs(subtotal - (total - subtotal)))
                for count, subtotal in states
                if count == 24
            ]
            best_gap = min((gap for _, gap in candidates))
            best_subtotals = [
                subtotal for subtotal, gap in candidates if gap == best_gap
            ]
            selected_subtotal = rng.choice(best_subtotals)
            state = (24, selected_subtotal)
            while state != (0, 0):
                previous, idx = states[state]
                visible_indices.add(idx)
                state = previous
    return visible_indices


def make_assignments(
    counts: pd.DataFrame, burden_column: str, seed: int
) -> pd.DataFrame:
    require_complete_counts(counts, burden_column)
    rng = random.Random(seed)
    r1_gpt_studies = choose_balanced_model_split(counts, burden_column, rng)
    rows = []
    count_lookup = (
        counts.set_index(["study_id", "source_model"])[burden_column]
        .astype(int)
        .to_dict()
    )
    studies = sorted(counts["study_id"].astype(str).unique())
    for study_id in studies:
        if study_id in r1_gpt_studies:
            rows.append(
                {
                    "study_id": study_id,
                    "assigned_reviewer": "R1",
                    "source_model": "gpt",
                    burden_column: count_lookup[study_id, "gpt"],
                }
            )
            rows.append(
                {
                    "study_id": study_id,
                    "assigned_reviewer": "R2",
                    "source_model": "claude",
                    burden_column: count_lookup[study_id, "claude"],
                }
            )
        else:
            rows.append(
                {
                    "study_id": study_id,
                    "assigned_reviewer": "R1",
                    "source_model": "claude",
                    burden_column: count_lookup[study_id, "claude"],
                }
            )
            rows.append(
                {
                    "study_id": study_id,
                    "assigned_reviewer": "R2",
                    "source_model": "gpt",
                    burden_column: count_lookup[study_id, "gpt"],
                }
            )
    assignments = pd.DataFrame(rows)
    visible_indices = choose_visible_assignments(assignments, burden_column, rng)
    assignments["uncertainty_status"] = [
        "visible" if idx in visible_indices else "hidden" for idx in assignments.index
    ]
    assignments["review_order"] = 0
    for reviewer in REVIEWERS:
        reviewer_indices = list(
            assignments.index[assignments["assigned_reviewer"] == reviewer]
        )
        rng.shuffle(reviewer_indices)
        for order, idx in enumerate(reviewer_indices, start=1):
            assignments.loc[idx, "review_order"] = order
    return assignments


def main():
    records = load_assessments(ROOT / "02_data")
    assignments = []
    for task, kinds, seed in [
        ("data", ["data"], SEED),
        ("rob", ["items", "groups"], SEED + 1),
    ]:
        rows = [row["original"] for kind in kinds for row in records[kind]]
        counts = (
            pd.DataFrame(rows)
            .groupby(["study_id", "source_model"])
            .size()
            .reset_index(name="rows")
        )
        generated = make_assignments(counts, "rows", seed)
        generated["task"] = task
        assignments.append(generated)
    generated = pd.concat(assignments, ignore_index=True)
    recorded = pd.read_csv(ROOT / "02_data/inputs/timing.csv")
    keys = ["study_id", "source_model", "task"]
    values = ["assigned_reviewer", "uncertainty_status", "review_order"]
    pd.testing.assert_frame_equal(
        generated.set_index(keys)[values].sort_index(),
        recorded.set_index(keys)[values].sort_index(),
        check_dtype=False,
    )
    output = ROOT / "03_analysis/results/current"
    output.mkdir(parents=True, exist_ok=True)
    generated.sort_values(["task", "assigned_reviewer", "review_order"]).to_csv(
        output / "randomization.csv", index=False
    )
    print("Randomization matches all 384 recorded sessions.")


if __name__ == "__main__":
    main()
