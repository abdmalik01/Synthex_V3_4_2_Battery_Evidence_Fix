"""Matplotlib renderer that consumes validated specifications, not domain models."""

from __future__ import annotations

import io
import math

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

from .models import AnalyticMeasurementRow, VisualizationSpec
from .specs import field_value


class VisualizationRenderer:
    def render_png(self, spec: VisualizationSpec, rows: list[AnalyticMeasurementRow]) -> bytes:
        if not spec.eligible:
            raise ValueError(f"Visualization is not eligible: {spec.reason}")
        fig = plt.figure(figsize=(8, 5.5))
        if spec.chart_type == "radar":
            self._radar(fig, spec, rows)
        else:
            axis = fig.add_subplot(111)
            self._cartesian(axis, spec, rows)
        fig.suptitle(spec.title)
        buffer = io.BytesIO()
        fig.savefig(buffer, format="png", dpi=180, bbox_inches="tight")
        plt.close(fig)
        return buffer.getvalue()

    def _cartesian(self, axis, spec, rows):
        x = [field_value(row, spec.x_field) for row in rows]
        y = [field_value(row, spec.y_field) for row in rows]
        if spec.chart_type == "bar":
            axis.bar([str(value) for value in x], y)
        elif spec.chart_type == "line":
            axis.plot(x, y, marker="o")
        elif spec.chart_type == "scatter":
            axis.scatter(x, y)
        elif spec.chart_type == "heatmap":
            axis.scatter(x, y, c=[row.value for row in rows], cmap="viridis")
        elif spec.chart_type == "contour":
            contour = axis.tricontourf(x, y, [row.value for row in rows], levels=8)
            plt.colorbar(contour, ax=axis, label=spec.units.get("y", "value"))
        axis.set_xlabel(spec.x_label or "x")
        axis.set_ylabel(spec.y_label or "y")

    def _radar(self, fig, spec, rows):
        axis = fig.add_subplot(111, polar=True)
        angles = np.linspace(0, 2 * np.pi, len(spec.radar_fields), endpoint=False).tolist()
        angles += angles[:1]
        for row in rows:
            values = np.array([field_value(row, field) for field in spec.radar_fields], dtype=float)
            # Explicit min-max policy is applied by metric across caller-selected rows.
            normalized = []
            for field, value in zip(spec.radar_fields, values):
                population = [field_value(candidate, field) for candidate in rows]
                lo, hi = min(population), max(population)
                normalized.append(1.0 if hi == lo else (value - lo) / (hi - lo))
            axis.plot(angles, normalized + normalized[:1], label=row.material_label or row.archive_id)
        axis.set_xticks(angles[:-1], spec.radar_fields)
        axis.legend(fontsize=8)
