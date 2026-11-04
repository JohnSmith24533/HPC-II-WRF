# WRF CPU measured status

Branch: `perf/wrf-cpu`. Numeric reports and large files live in `.wrf-cpu/`.

| Label | Case | Tier | Check | Comparison | Ranks | Wall s | Median step s | IO write s |
|---|---|---|---|---|---|---|---|---|
| baseline | b_wave | single | PASS | reference | 4 | 2.378 | 0.169820 | 0.285 |
| baseline | b_wave | short | PASS | reference | 4 | 2.684 | 0.042730 | 0.383 |
| baseline | b_wave | full | PASS | reference | 4 | 39.822 | 0.043180 | 6.292 |
| baseline | b_wave | restart | PASS | PASS | 4 | 21.942 | 0.043580 | 3.323 |
| baseline | quarter_ss | single | PASS | reference | 4 | 2.174 | 0.104100 | 0.168 |
| baseline | quarter_ss | short | PASS | reference | 4 | 2.399 | 0.019850 | 0.206 |
| baseline | quarter_ss | full | PASS | reference | 4 | 10.702 | 0.023865 | 1.695 |
| baseline | quarter_ss | restart | PASS | PASS | 4 | 7.125 | 0.024515 | 0.990 |
| baseline | les | single | PASS | reference | 4 | 2.179 | 0.103630 | 0.199 |
| baseline | les | short | PASS | reference | 4 | 3.306 | 0.018595 | 0.203 |
| baseline | les | full | PASS | reference | 4 | 72.750 | 0.018810 | 2.454 |
| baseline | les | restart | PASS | PASS | 4 | 37.636 | 0.019020 | 0.918 |
| baseline | convrad | single | PASS | reference | 4 | 3.466 | 0.922550 | 0.574 |
| baseline | convrad | short | PASS | reference | 4 | 22.175 | 0.152480 | 0.764 |
| baseline | convrad | full | PASS | reference | 4 | 126.132 | 0.155105 | 6.040 |
| baseline | convrad | restart | PASS | PASS | 4 | 64.553 | 0.150030 | 3.436 |
| baseline | conus12 | single | PASS | reference | 16 | 46.916 | 17.990890 | 13.819 |
| baseline | conus12 | short | PASS | reference | 16 | 54.735 | 0.834235 | 13.888 |
| baseline | conus12 | full | PASS | reference | 16 | 1330.268 | 0.967965 | 170.882 |
| baseline | conus12 | restart | PASS | PASS | 16 | 687.781 | 0.991770 | 82.120 |
| replay | b_wave | single | PASS | PASS | 4 | 2.401 | 0.185620 | 0.312 |
| replay | b_wave | short | PASS | PASS | 4 | 2.629 | 0.044285 | 0.335 |
| replay | b_wave | full | PASS | PASS | 4 | 38.544 | 0.042260 | 5.991 |
| replay | b_wave | restart | PASS | PASS | 4 | 21.421 | 0.042880 | 3.294 |
| replay | quarter_ss | single | PASS | PASS | 4 | 2.170 | 0.102800 | 0.167 |
| replay | quarter_ss | short | PASS | PASS | 4 | 2.354 | 0.019430 | 0.205 |
| replay | quarter_ss | full | PASS | PASS | 4 | 10.730 | 0.023810 | 1.826 |
| replay | quarter_ss | restart | PASS | PASS | 4 | 7.092 | 0.024145 | 0.967 |
| replay | les | single | PASS | PASS | 4 | 2.368 | 0.106800 | 0.363 |
| replay | les | short | PASS | PASS | 4 | 3.285 | 0.018600 | 0.203 |
| replay | les | full | PASS | PASS | 4 | 74.612 | 0.019630 | 1.656 |
| replay | les | restart | PASS | PASS | 4 | 38.129 | 0.018940 | 0.974 |
| replay | convrad | single | PASS | PASS | 4 | 3.566 | 0.999100 | 0.668 |
| replay | convrad | short | PASS | PASS | 4 | 22.492 | 0.156195 | 0.601 |
| replay | convrad | full | PASS | PASS | 4 | 125.644 | 0.154585 | 5.829 |
| replay | convrad | restart | PASS | PASS | 4 | 63.777 | 0.149445 | 3.277 |
| replay | conus12 | single | PASS | PASS | 16 | 46.774 | 17.962150 | 13.802 |
| replay | conus12 | short | PASS | PASS | 16 | 54.620 | 0.832040 | 13.951 |
| replay | conus12 | full | PASS | PASS | 16 | 1338.184 | 0.967755 | 172.692 |
| replay | conus12 | restart | PASS | PASS | 16 | 688.559 | 0.990225 | 82.199 |

## Baseline physical diagnostics

Budget changes below are measured inventories, not conservation assertions for domains with boundary fluxes or physical sources/sinks.

| Case | Final max rain mm | Wet area >=0.1 mm % | Final max TKE | Dry mass relative change | Atmospheric water change kg | Dry energy proxy relative change |
|---|---|---|---|---|---|---|
| b_wave | 0 | 0 | — | 1.05022e-11 | 0 | -4.6683e-05 |
| quarter_ss | 36.613 | 10.8864 | 75.082 | 0.000156856 | 8.38759e+09 | 0.0017097 |
| les | 0 | 0 | 1.64789 | 1.36664e-11 | 275.328 | 0.00162174 |
| convrad | 0 | 0 | — | 4.35358e-11 | 1.00619e+09 | -0.000305256 |
| conus12 | 54.08 | 30.0601 | 13.5525 | 4.61781e-05 | 2.38281e+13 | 0.000494137 |

Golden reference: published.

PASS in this summary reflects saved reports. `publish.py` rereads current NetCDF files before accepting a golden reference.
