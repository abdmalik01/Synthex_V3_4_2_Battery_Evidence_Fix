from __future__ import annotations
import io
import math
import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
from .models import SensorRecord


def _sample_label(sample, idx):
    sid = sample.sample_id or sample.material or f"Sample {idx+1}"
    if sample.source_paper_title:
        short = sample.source_paper_title[:34] + ('…' if len(sample.source_paper_title) > 34 else '')
        return f"{short} | {sid}"
    return sid


def selectivity_matrix(record: SensorRecord) -> pd.DataFrame:
    rows = []
    for i, sample in enumerate(record.samples):
        p = sample.performance
        if not p or not p.selectivity:
            continue
        target = p.selectivity.target_analyte or (sample.testing_conditions.target_analyte if sample.testing_conditions else None) or "Target"
        for entry in p.selectivity.entries:
            value = entry.selectivity_ratio
            # Computation is only used when both responses are explicitly extracted.
            if value is None and entry.target_response is not None and entry.interferent_response not in (None, 0):
                value = entry.target_response / entry.interferent_response
            if value is not None:
                rows.append({"sample": _sample_label(sample, i), "pair": f"{target}/{entry.interferent or 'interferent'}", "ratio": value})
    if not rows:
        return pd.DataFrame()
    return pd.DataFrame(rows).pivot_table(index="sample", columns="pair", values="ratio", aggfunc="mean")


def plot_selectivity_heatmap(record: SensorRecord):
    matrix = selectivity_matrix(record)
    if matrix.empty:
        return None
    fig, ax = plt.subplots(figsize=(max(7, 1.25 * len(matrix.columns)), max(4, 0.8 * len(matrix.index) + 2)))
    im = ax.imshow(matrix.values, aspect="auto")
    fig.colorbar(im, ax=ax, label="Selectivity ratio")
    ax.set_xticks(range(len(matrix.columns)), matrix.columns, rotation=35, ha="right")
    ax.set_yticks(range(len(matrix.index)), matrix.index)
    ax.set_xlabel("Target / interferent")
    ax.set_ylabel("Sample")
    ax.set_title("Selectivity heat map")
    for r in range(matrix.shape[0]):
        for c in range(matrix.shape[1]):
            v = matrix.iloc[r, c]
            if pd.notna(v):
                ax.text(c, r, f"{v:.2g}", ha="center", va="center")
    fig.tight_layout()
    return fig


def response_time_points(record: SensorRecord) -> pd.DataFrame:
    rows = []
    for i, sample in enumerate(record.samples):
        p = sample.performance
        if not p or not p.response_time or not p.response_time.value:
            continue
        rt = p.response_time
        y = rt.value.normalized_value if rt.value.normalized_value is not None else rt.value.value
        unit = rt.value.normalized_unit or rt.value.unit
        tc = sample.testing_conditions
        temp_q = rt.operating_temperature or (tc.operating_temperature if tc else None)
        conc_q = rt.concentration or (tc.concentration if tc else None)
        temp = None if not temp_q else (temp_q.normalized_value if temp_q.normalized_value is not None else temp_q.value)
        conc = None if not conc_q else (conc_q.normalized_value if conc_q.normalized_value is not None else conc_q.value)
        target = rt.analyte or (tc.target_analyte if tc else None)
        if y is not None:
            rows.append({
                "sample": _sample_label(sample, i),
                "source_paper": sample.source_paper_title,
                "material": sample.material,
                "sensor_type": sample.sensor_type,
                "target_analyte": target,
                "temperature_C": temp,
                "concentration_ppm": conc,
                "response_time": y,
                "response_time_unit": unit,
                "criterion": rt.criterion,
            })
    return pd.DataFrame(rows)


def response_time_groups(record: SensorRecord) -> dict[str, pd.DataFrame]:
    """Return scientifically safer contour groups: same material + target + sensor type."""
    df = response_time_points(record)
    if df.empty:
        return {}
    usable = df.dropna(subset=["material", "target_analyte", "temperature_C", "concentration_ppm", "response_time"]).copy()
    groups = {}
    for keys, g in usable.groupby(["material", "target_analyte", "sensor_type"], dropna=False):
        material, target, sensor_type = keys
        if len(g) >= 4 and g["temperature_C"].nunique() >= 2 and g["concentration_ppm"].nunique() >= 2:
            label = f"{material} | {target} | {sensor_type or 'sensor'}"
            groups[label] = g
    return groups


def plot_response_time_contour(record: SensorRecord, group_label: str | None = None):
    groups = response_time_groups(record)
    if not groups:
        return None
    if group_label is None or group_label not in groups:
        group_label = max(groups, key=lambda k: len(groups[k]))
    df = groups[group_label]
    try:
        import matplotlib.tri as mtri
        tri = mtri.Triangulation(df["temperature_C"].to_numpy(float), df["concentration_ppm"].to_numpy(float))
        if len(tri.triangles) == 0:
            return None
        fig, ax = plt.subplots(figsize=(8, 5.5))
        contour = ax.tricontourf(tri, df["response_time"].to_numpy(float), levels=12)
        unit = df["response_time_unit"].dropna().iloc[0] if not df["response_time_unit"].dropna().empty else "reported unit"
        fig.colorbar(contour, ax=ax, label=f"Response time ({unit})")
        ax.scatter(df["temperature_C"], df["concentration_ppm"], s=28)
        ax.set_xlabel("Operating temperature (°C)")
        ax.set_ylabel("Analyte concentration (ppm normalized where possible)")
        ax.set_title(f"Response-time contour map\n{group_label}")
        fig.tight_layout()
        return fig
    except Exception:
        return None


def _metric_value(sample, metric):
    p = sample.performance
    if not p:
        return None
    if metric == "Selectivity":
        vals = [e.selectivity_ratio for e in p.selectivity.entries if e.selectivity_ratio is not None] if p.selectivity else []
        return max(vals) if vals else None
    if metric == "Sensitivity":
        return p.sensitivity.value.value if p.sensitivity and p.sensitivity.value else None
    if metric == "Detection capability":
        v = p.limit_of_detection.value.value if p.limit_of_detection and p.limit_of_detection.value else None
        return None if v in (None, 0) else 1.0 / v
    if metric == "Response speed":
        q = p.response_time.value if p.response_time and p.response_time.value else None
        v = None if not q else (q.normalized_value if q.normalized_value is not None else q.value)
        return None if v in (None, 0) else 1.0 / v
    if metric == "Recovery speed":
        q = p.recovery_time.value if p.recovery_time and p.recovery_time.value else None
        v = None if not q else (q.normalized_value if q.normalized_value is not None else q.value)
        return None if v in (None, 0) else 1.0 / v
    return None


def radar_groups(record: SensorRecord) -> dict[str, list[tuple[str, object]]]:
    """Group radar comparisons by target analyte + sensor type to avoid apples-to-oranges plots."""
    metrics = ["Selectivity", "Response speed", "Recovery speed", "Sensitivity", "Detection capability"]
    buckets = {}
    for i, sample in enumerate(record.samples):
        tc = sample.testing_conditions
        target = tc.target_analyte if tc else None
        sensor_type = sample.sensor_type
        if not target or not sensor_type:
            continue
        vals = [_metric_value(sample, m) for m in metrics]
        if sum(v is not None and math.isfinite(float(v)) for v in vals) < 3:
            continue
        key = f"{target} | {sensor_type}"
        buckets.setdefault(key, []).append((_sample_label(sample, i), vals))
    return {k:v for k,v in buckets.items() if len(v) >= 2}


def plot_radar(record: SensorRecord, group_label: str | None = None):
    metrics = ["Selectivity", "Response speed", "Recovery speed", "Sensitivity", "Detection capability"]
    groups = radar_groups(record)
    if not groups:
        return None
    if group_label is None or group_label not in groups:
        group_label = max(groups, key=lambda k: len(groups[k]))
    items = groups[group_label]
    labels = [x[0] for x in items]
    raw = [x[1] for x in items]
    arr = np.array([[np.nan if v is None else float(v) for v in row] for row in raw], dtype=float)
    norm = np.zeros_like(arr)
    for j in range(arr.shape[1]):
        col = arr[:, j]
        mask = np.isfinite(col)
        if not mask.any():
            norm[:, j] = np.nan
            continue
        lo, hi = np.nanmin(col), np.nanmax(col)
        norm[mask, j] = 1.0 if hi == lo else (col[mask] - lo) / (hi - lo)
        norm[~mask, j] = np.nan
    angles = np.linspace(0, 2 * np.pi, len(metrics), endpoint=False).tolist()
    angles += angles[:1]
    fig = plt.figure(figsize=(7.5, 7.5))
    ax = fig.add_subplot(111, polar=True)
    for label, row in zip(labels, norm):
        vals = np.nan_to_num(row, nan=0.0).tolist()
        vals += vals[:1]
        ax.plot(angles, vals, linewidth=2, label=label)
        ax.fill(angles, vals, alpha=0.08)
    ax.set_xticks(angles[:-1])
    ax.set_xticklabels(metrics)
    ax.set_ylim(0, 1)
    ax.set_yticklabels([])
    ax.set_title(f"Normalized sensor-performance radar plot\n{group_label}", pad=22)
    ax.legend(loc="upper right", bbox_to_anchor=(1.32, 1.14), fontsize=8)
    fig.tight_layout()
    return fig

def figure_to_png_bytes(fig) -> bytes:
    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=220, bbox_inches="tight")
    buf.seek(0)
    return buf.read()
