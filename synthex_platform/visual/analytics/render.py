"""Matplotlib renderer that consumes validated specifications, not domain models."""

from __future__ import annotations

import io

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

from .models import AnalyticMeasurementRow, VisualizationSpec
from .specs import display_label_with_unit, field_display_name, field_value


def observed_rectangular_grid(
    rows: list[AnalyticMeasurementRow],
    x_field: str | None,
    y_field: str | None,
    z_field: str | None,
) -> tuple[list[float], list[float], np.ndarray] | None:
    """Return an exact observed-value matrix only when every grid cell occurs once."""
    if not x_field or not y_field or not z_field:
        return None
    coordinates: dict[tuple[float, float], float] = {}
    for row in rows:
        x = field_value(row, x_field)
        y = field_value(row, y_field)
        z = field_value(row, z_field)
        if not all(isinstance(value, (int, float)) and not isinstance(value, bool) for value in (x, y, z)):
            continue
        coordinate = (float(x), float(y))
        if coordinate in coordinates:
            return None
        coordinates[coordinate] = float(z)
    if not coordinates:
        return None
    x_values = sorted({coordinate[0] for coordinate in coordinates})
    y_values = sorted({coordinate[1] for coordinate in coordinates})
    if len(coordinates) != len(x_values) * len(y_values):
        return None
    matrix = np.array(
        [[coordinates[(x, y)] for x in x_values] for y in y_values],
        dtype=float,
    )
    return x_values, y_values, matrix


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

    @staticmethod
    def _numeric(value) -> bool:
        return isinstance(value, (int, float)) and not isinstance(value, bool)

    def _usable(self, spec: VisualizationSpec, rows: list[AnalyticMeasurementRow]) -> list[AnalyticMeasurementRow]:
        usable: list[AnalyticMeasurementRow] = []
        for row in rows:
            x = field_value(row, spec.x_field)
            y = field_value(row, spec.y_field)
            if spec.chart_type == "bar":
                valid = x is not None and self._numeric(y)
            else:
                valid = self._numeric(x) and self._numeric(y)
            if spec.chart_type in {"heatmap", "contour"}:
                valid = valid and self._numeric(field_value(row, spec.z_field))
            if valid:
                usable.append(row)
        return usable

    @staticmethod
    def _display_label(field: str | None) -> str:
        return field_display_name(field)

    def _series_groups(self, spec: VisualizationSpec, rows: list[AnalyticMeasurementRow]):
        if not spec.series_field:
            return [(None, rows)]
        grouped: dict[str, list[AnalyticMeasurementRow]] = {}
        for row in rows:
            label = field_value(row, spec.series_field)
            grouped.setdefault(str(label or "Unspecified"), []).append(row)
        return sorted(grouped.items(), key=lambda item: item[0].casefold())

    def _cartesian(self, axis, spec, rows):
        usable = self._usable(spec, rows)
        if spec.chart_type == "bar":
            x = [field_value(row, spec.x_field) for row in usable]
            y = [field_value(row, spec.y_field) for row in usable]
            axis.bar([str(value) for value in x], y)
        elif spec.chart_type in {"line", "scatter"}:
            for label, group in self._series_groups(spec, usable):
                ordered = sorted(group, key=lambda row: float(field_value(row, spec.x_field)))
                x = [field_value(row, spec.x_field) for row in ordered]
                y = [field_value(row, spec.y_field) for row in ordered]
                if spec.chart_type == "line":
                    axis.plot(x, y, marker="o", label=label)
                else:
                    axis.scatter(x, y, label=label)
            if spec.series_field:
                axis.legend(fontsize=8)
        elif spec.chart_type in {"heatmap", "contour"}:
            x = [field_value(row, spec.x_field) for row in usable]
            y = [field_value(row, spec.y_field) for row in usable]
            z = [field_value(row, spec.z_field) for row in usable]
            z_label = self._display_label(spec.z_label or spec.z_field)
            z_unit = spec.units.get("z")
            colorbar_label = display_label_with_unit(z_label, z_unit)
            grid = observed_rectangular_grid(usable, spec.x_field, spec.y_field, spec.z_field)
            if spec.chart_type == "heatmap":
                if grid is not None:
                    grid_x, grid_y, grid_z = grid
                    plotted = axis.pcolormesh(grid_x, grid_y, grid_z, cmap="viridis", shading="auto")
                else:
                    # Incomplete surfaces remain observed points; missing cells are never manufactured.
                    plotted = axis.scatter(x, y, c=z, cmap="viridis", marker="s", s=220)
                axis.figure.colorbar(plotted, ax=axis, label=colorbar_label)
            else:
                if grid is not None:
                    grid_x, grid_y, grid_z = grid
                    contour = axis.contourf(grid_x, grid_y, grid_z, levels=8, cmap="viridis")
                else:
                    contour = axis.tricontourf(x, y, z, levels=8, cmap="viridis")
                axis.figure.colorbar(contour, ax=axis, label=colorbar_label)
                if spec.show_measured_points:
                    axis.scatter(
                        x,
                        y,
                        facecolors="none",
                        edgecolors="black",
                        linewidths=0.8,
                        s=28,
                        zorder=3,
                    )

        x_label = self._display_label(spec.x_label or spec.x_field)
        y_label = self._display_label(spec.y_label or spec.y_field)
        x_unit = spec.units.get("x")
        y_unit = spec.units.get("y")
        axis.set_xlabel(display_label_with_unit(x_label or "x", x_unit))
        axis.set_ylabel(display_label_with_unit(y_label or "y", y_unit))

    def _radar(self, fig, spec, rows):
        axis = fig.add_subplot(111, polar=True)
        angles = np.linspace(0, 2 * np.pi, len(spec.radar_fields), endpoint=False).tolist()
        angles += angles[:1]
        for row in rows:
            values = np.array([field_value(row, field) for field in spec.radar_fields], dtype=float)
            normalized = []
            for field, value in zip(spec.radar_fields, values):
                population = [field_value(candidate, field) for candidate in rows]
                lo, hi = min(population), max(population)
                normalized.append(1.0 if hi == lo else (value - lo) / (hi - lo))
            axis.plot(angles, normalized + normalized[:1], label=row.material_label or row.archive_id)
        axis.set_xticks(angles[:-1], spec.radar_fields)
        axis.legend(fontsize=8)
