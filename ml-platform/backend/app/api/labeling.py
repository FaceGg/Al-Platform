"""
Auto-labeling API endpoints: rule-based and similarity-based labeling.
"""
import re
from fastapi import APIRouter, Body
import numpy as np

router = APIRouter(prefix="/api/labeling", tags=["labeling"])


# -------------------------------------------------------------------------------
#  Rule-based labeling
# -------------------------------------------------------------------------------

@router.post("/rules")
def label_by_rules(
    data: list = Body(...),
    columns: list = Body(...),
    rules: list = Body(...),
):
    """Apply rule-based auto-labeling to tabular data.

    Args:
        data: List of rows, each row is a list of values.
        columns: List of column names matching data columns.
        rules: List of rule dicts: {column, condition, label}.
            conditions: equals, contains, greater_than, less_than, in, regex.

    Returns:
        {labels: [{row_index, label, matched_rule}], unmatched_count: int}
    """
    # Build column index map
    col_index = {col: i for i, col in enumerate(columns)}
    results = []
    unmatched = 0

    for row_idx, row in enumerate(data):
        matched = False
        for rule_idx, rule in enumerate(rules):
            column = rule.get("column", "")
            condition = rule.get("condition", "equals")
            label = rule.get("label", "")
            rule_value = rule.get("value")

            if column not in col_index:
                continue

            cell_value = row[col_index[column]]
            cell_str = str(cell_value) if cell_value is not None else ""

            if _evaluate_condition(cell_str, condition, rule_value):
                results.append({
                    "row_index": row_idx,
                    "label": label,
                    "matched_rule": rule_idx,
                    "rule": rule,
                })
                matched = True
                break  # First matching rule wins

        if not matched:
            unmatched += 1
            results.append({
                "row_index": row_idx,
                "label": None,
                "matched_rule": None,
                "rule": None,
            })

    return {
        "labels": results,
        "total": len(data),
        "matched": len(data) - unmatched,
        "unmatched_count": unmatched,
    }


def _evaluate_condition(cell_value: str, condition: str, rule_value):
    """Evaluate whether a cell value matches a condition."""
    if condition == "equals":
        return cell_value == str(rule_value) if rule_value is not None else False
    elif condition == "contains":
        return str(rule_value).lower() in cell_value.lower() if rule_value is not None else False
    elif condition == "greater_than":
        try:
            return float(cell_value) > float(rule_value)
        except (ValueError, TypeError):
            return False
    elif condition == "less_than":
        try:
            return float(cell_value) < float(rule_value)
        except (ValueError, TypeError):
            return False
    elif condition == "in":
        if isinstance(rule_value, list):
            return cell_value in [str(v) for v in rule_value]
        return cell_value == str(rule_value) if rule_value is not None else False
    elif condition == "regex":
        try:
            return bool(re.search(str(rule_value), cell_value))
        except re.error:
            return False
    else:
        return False


# -------------------------------------------------------------------------------
#  Similarity-based labeling (KNN)
# -------------------------------------------------------------------------------

@router.post("/similarity")
def label_by_similarity(
    unlabeled: list = Body(...),
    labeled: list = Body(...),
    columns: list = Body(...),
    k: int = Body(default=3),
    metric: str = Body(default="cosine"),
):
    """Label unlabeled samples using KNN similarity to labeled samples.

    Args:
        unlabeled: List of feature rows [[val1, val2, ...], ...].
        labeled: List of dicts [{features: [val1, val2, ...], label: str}, ...].
        columns: Column names (unused for computation but included for consistency).
        k: Number of nearest neighbors to consider. Default 3.
        metric: Distance metric: 'cosine', 'euclidean', 'dot'. Default 'cosine'.

    Returns:
        {predictions: [{row_index, predicted_label, confidence, neighbors}]}
    """
    if not labeled:
        return {"predictions": [], "error": "No labeled samples provided"}

    if not unlabeled:
        return {"predictions": []}

    # Extract feature vectors and labels
    labeled_features = []
    labeled_labels = []
    for item in labeled:
        feats = item.get("features", [])
        label = item.get("label")
        if feats and label is not None:
            labeled_features.append([_to_float(v) for v in feats])
            labeled_labels.append(label)

    if not labeled_features:
        return {"predictions": [], "error": "No valid labeled samples with features and labels"}

    unlabeled_features = []
    for row in unlabeled:
        unlabeled_features.append([_to_float(v) for v in row])

    # Convert to numpy arrays
    X_labeled = np.array(labeled_features, dtype=np.float64)
    X_unlabeled = np.array(unlabeled_features, dtype=np.float64)

    # Normalize if cosine
    if metric == "cosine":
        X_labeled = _l2_normalize_rows(X_labeled)
        X_unlabeled = _l2_normalize_rows(X_unlabeled)

    predictions = []
    for i, unlabeled_row in enumerate(X_unlabeled):
        if metric == "cosine" or metric == "dot":
            # Higher = more similar
            sims = X_labeled.dot(unlabeled_row)
            top_k = min(k, len(sims))
            top_indices = np.argsort(sims)[::-1][:top_k]
            top_scores = sims[top_indices]
        elif metric == "euclidean":
            # Lower distance = more similar
            diffs = X_labeled - unlabeled_row
            distances = np.sqrt(np.sum(diffs * diffs, axis=1))
            top_k = min(k, len(distances))
            top_indices = np.argsort(distances)[:top_k]
            max_dist = distances.max() + 1e-10
            top_scores = 1.0 - distances[top_indices] / max_dist
        else:
            sims = X_labeled.dot(unlabeled_row)
            top_k = min(k, len(sims))
            top_indices = np.argsort(sims)[::-1][:top_k]
            top_scores = sims[top_indices]

        # Majority vote among neighbors
        neighbor_labels = [labeled_labels[idx] for idx in top_indices]
        label_counts = {}
        for lbl in neighbor_labels:
            label_counts[lbl] = label_counts.get(lbl, 0) + 1
        predicted_label = max(label_counts, key=label_counts.get)
        confidence = label_counts[predicted_label] / top_k

        neighbors = [
            {
                "label": labeled_labels[idx],
                "score": round(float(top_scores[j]), 4),
            }
            for j, idx in enumerate(top_indices)
        ]

        predictions.append({
            "row_index": i,
            "predicted_label": predicted_label,
            "confidence": round(float(confidence), 4),
            "neighbors": neighbors,
        })

    return {"predictions": predictions}


def _to_float(value):
    """Convert a value to float, defaulting to 0.0."""
    try:
        return float(value)
    except (ValueError, TypeError):
        return 0.0


def _l2_normalize_rows(arr):
    """L2-normalize each row of a numpy array. Returns array of same shape."""
    norms = np.linalg.norm(arr, axis=1, keepdims=True)
    norms = np.where(norms == 0, 1e-10, norms)
    return arr / norms
