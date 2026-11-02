"""Keep row-matching aliases separate from literal reference values."""


def matching_row(row, spec):
    result = dict(row)
    for key in spec.get("match_fields_from_original", []):
        result[key] = row["source_identity"][key]
    if "week" in result:
        result["week"] = spec.get("week_aliases", {}).get(
            str(result["week"]), result["week"]
        )
    for override in spec.get("encoding_matching_values", []):
        if row.get("source_identity") == override["source_identity"]:
            result.update(override["set"])
    return result


def matches_context(row, context, spec):
    candidate = matching_row(row, spec)
    return all((candidate.get(k) == v for k, v in context.items()))
