# Real-paper replay benchmark

This benchmark does **not** pretend to be live Gemini extraction. It contains compact expected-value records derived from published source pages so that schema behavior, normalization, batch merging, heat maps and radar plots can be tested offline.

Cases included:

1. Wang et al., *Advanced Functional Materials* (2025), DOI `10.1002/adfm.202419057`: In2O3 SRLS NO2 sensor; response 460.9 at 10 ppm; response/recovery 27/570 s; calibration slope 56.91 ppm^-1; selectivity stated as response ratio >400.
2. *RSC Advances* (2024), DOI `10.1039/D3RA07507A`: 2%Au/1%ZnO/In2O3 isopropanol sensor; t90 response/recovery 78/49 s at 100 ppm.
3. *Zeitschrift für Naturforschung B* (2025), DOI `10.1515/znb-2024-0113`: Ni–In2O3/ZnO H2S sensor; 4.4/5.2 s at 100 ppm and 300 °C; LOD 0.57 ppm; qualitative H2S selectivity.
4. *Sensors* (2026), DOI `10.3390/s26154675`: ZnO / Dy-doped ZnO / Y-doped ZnO response and response/recovery table; explicit selectivity inversion ratios used as benchmark entries.

Use `python benchmark/build_expected_records.py`, then `pytest -q`.

## Li2FeTiO4 battery benchmark

`benchmark_battery_material.py` reports separate structural, value, condition-association, and provenance metrics.
The five gold performance facts must match the 700 °C Li2FeTiO4 sample, property, value, unit, applicable cycle
and method, and value-bearing evidence. The paper's conflicting 0.1 C versus 1 C long-term cycling statements
are represented explicitly; the benchmark does not select one rate merely to award condition credit.

Benchmark extraction is paper-only. Serper enrichment is not part of this scoring path.
