# Completed WRF CPU baseline and golden reference

Branch: `perf/wrf-cpu`. No `git push` was performed.

Official unmodified WRF v4.7.1 source: `f52c197ed39d12e087d02c50f412d90d418f6186`.

| Case | Original namelist grid | Full simulation | MPI ranks |
|---|---|---|---|
| Baroclinic wave | 41 × 81 × 65 | 5 days | 4 |
| Quarter-circle supercell | 42 × 42 × 41 | 1 hour | 4 |
| LES | 40 × 40 × 40 | 1 hour | 4 |
| Convective-radiative | 101 × 101 × 35 | 1 hour | 4 |
| CONUS 12 km, 2019 winter storm | 425 × 300 × 50 | 12 hours | 16 |

All five cases completed baseline and independent replay at single-step, short, full and restart lengths: **40 successful execution checks, 25 numerical comparisons, 24,057 bitwise metric rows, 5,428,736,323 numerical values compared; all errors zero.**

Golden reference: **15 case/tier references, 120 sealed files, including 75 NetCDF history files.** Final audit checked actual grid, spacing, physics, precision, MPI count, timestamps, mandatory fields, immutable hashes and identity with the numerically verified baseline source files.

Manifest SHA-256: `e70433e193b149104dbb5967b1013c449d519f25ef9e51362a85c77bcb67c697`.

The verifier/artifact-integrity suite passed 13 tests. Source/build provenance passed 11 checks. Ccache is enabled for C compilation; installed ccache does not support Fortran. Incremental build artifacts and the pinned environment are retained.

Evidence and reproduction:

- [Measured timing and physical diagnostics](RESULTS.md)
- [Workflow, commands and documented case details](README.md)
- [Current-artifact completion audit](../../.wrf-cpu/completion-audit.json)
- [Golden manifest](../../.wrf-cpu/golden/manifest.json)
- [Sealed verification-tool snapshot](../../.wrf-cpu/baseline/harness/)

Documented case handling: dry LES omits the officially undefined LH history diagnostic, with original evidence retained. CONUS restart uses the official `write_hist_at_0h_rst=false` default and compares all fields at all six computed hourly outputs. The supplied one-hour convrad case does not establish multiweek equilibrium; mass/water/energy inventories are regression diagnostics rather than unconditional closed-budget assertions.

Build/run outputs and frozen inputs remain local under `.wrf-cpu/`; model source code is unchanged.
