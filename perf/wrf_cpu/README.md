# WRF CPU baseline / golden reference

工作分支固定為 `perf/wrf-cpu`。本流程先保存未修改 WRF v4.7.1
(`f52c197ed39d12e087d02c50f412d90d418f6186`) 的執行結果與性能，再用相同執行檔、
固定輸入獨立重跑；五個案例都通過後才能發布 golden reference。
目前實際進度以 `.wrf-cpu/logs/`、Slurm 與各 run 的 JSON 報告為準；本說明不代表已通過。

| 案例 | 原始 namelist 網格 e_we × e_sn × e_vert | 單步 | 短程 | 完整 | MPI ranks |
|---|---|---|---|---|---|
| Baroclinic wave | 41 × 81 × 65 | 600 s | 3600 s | 5 天 | 4 |
| Quarter-circle supercell | 42 × 42 × 41 | 12 s | 120 s | 1 小時 | 4 |
| LES | 40 × 40 × 40 | 1 s | 60 s | 1 小時 | 4 |
| Convective-radiative | 101 × 101 × 35 | 5 s | 600 s | 1 小時 | 4 |
| CONUS 12 km | 425 × 300 × 50 | 72 s | 720 s | 12 小時 | 16 |

這些是 WRF 的 staggered dimension；mass grid 各方向通常少一點。所有案例保留原始網格、
時間步與物理方案。單步／短程只改時長與輸出頻率，完整時長取自原始 namelist。
LES 完整執行超過說明文件要求的 30 分鐘 spin-up；convrad 的 1 小時是隨附展示案例，
不宣稱已達需要數週至數月的對流輻射平衡。

CONUS 使用 NCAR v4.4 官方 [2019 冬季風暴資料](https://www2.mmm.ucar.edu/wrf/users/benchmark/v44/benchdata_v44.html)，
從 2019-11-26 12:00 起跑 12 小時；該資料可供 WRF V4 使用。隨附的 v4.4 GNU/Intel
輸出保留供背景比較；本機 v4.7.1 的 golden 必須由本機未修改版本生成，不能把不同版本輸出當成 bitwise reference。
下載檔 SHA-256：`30110ce5b03b2c93b2f4e8081e24d8c83eb7be7e6bccb657a69b69b2ed953d50`。

## 建置

從 repo 根目錄、可連網的登入節點執行：

```bash
bash perf/wrf_cpu/setup.sh
sbatch --output=.wrf-cpu/logs/build-%j.log perf/wrf_cpu/build.sh
```

`setup.sh` 依照 `conda-linux-64.lock` 在 `.wrf-cpu/env` 安裝此 baseline 的確切依賴，取得固定官方 MMM-physics tag，核對 CONUS
下載檔，並完成兩種 CMake 配置。計算節點僅執行編譯，避免 CMake 的 manage_externals
在無對外網路的節點卡住。需要先有 repo 的 `phys/noahmp`、`phys/MYNN-EDMF` 子模組。
所有安裝與快取都留在工作樹，不更動系統套件。

固定 GNU 10.4.0 / OpenMPI 5.0.2、MPI 開啟、OpenMP 關閉、WRF REAL=4、
GNU 原始 `-O2 -ftree-vectorize -funroll-loops`；不使用 fast-math 或額外改變算術的選項。
`gnu.cmake` 明確列出旗標。CMake 的標準相容性旗標仍由官方建置檔產生。

`ccache` 僅啟用於 C compiler；它不支援本流程主要的 Fortran 編譯。後續 Fortran
build 時間主要靠保留 Ninja/CMake 的增量建置目錄縮短，不應把 C cache 命中誤報為
全部 WRF 已快取。統計存於 `baseline/ccache.txt`。

`build.sh` 拒絕模型 tracked sources 的未提交修改。`baseline/` 保存官方來源 tar、
子模組／MMM-physics 版本與 tar、compiler/MPI/module 資訊、Conda explicit lock、pip
版本、CMakeCache、執行檔 SHA-256 與 CPU 資訊。CMake 的 `dirty` 字樣可能來自本流程
的 `.gitignore`；模型本身必須仍與官方 commit 一致。

## 執行與固定輸入

先確認 build job 成功，且 `.wrf-cpu/baseline/build-complete.txt` 存在，再執行：

```bash
sbatch --output=.wrf-cpu/logs/baseline-%j.log perf/wrf_cpu/run.slurm --label baseline
# 前一工作成功完成後，再提交獨立重跑
sbatch --output=.wrf-cpu/logs/replay-%j.log perf/wrf_cpu/run.slurm --label replay --against baseline
```

每個案例依序跑 `single short full restart`。完整執行在中點寫 restart，restart
再跑後半段並與連續執行重疊時間比較。Slurm 設定適用目前 development 分區／acd110018
帳號；目前帳號可能僅允許單一提交工作，因此範例依序提交。

首次 `ideal` 一律用 1 MPI rank 產生初始場，存於 `inputs/<case>/` 並記錄雜湊。
LES/convrad 原始初始化含亂數，所以後續候選版本必須重用這份輸入，不再次執行 ideal。
CONUS 保存官方初始、邊界與 Thompson 表格。另將 baseline 的輻射／地表等 runtime 資料複製至 `runtime/ideal` 與 `runtime/real`，保存每檔雜湊；候選版本同樣使用這份凍結資料。TKE 預設只在 restart stream，流程以
runtime iofields 為 LES/supercell 加入 TKE history，不修改 Registry 或核心程式。

可用 `--cases les quarter_ss`、`--tiers single short` 選取子集。子集只供診斷，不能
代替全部完成。相同 label 的已完成執行可接續；失敗或未完成目錄不會被自動覆蓋，
需先查明原因，再使用新 label 保留舊證據。

## 官方 LES 的未定義 LH 診斷

原始 LES (`sf_sfclay_physics=1, isfflx=2`) 的新版 MM5 wrapper 只把 `isfflx==1`
轉成真值（`phys/module_sf_sfclayrev.F`），所以 MMM-physics
`sf_sfclayrev.F90` 跳過 `LH` 賦值；wrapper 仍把未初始化的 `lh_hv` 複製到輸出。
實跑觀察到 LH 最大達約 3e37 W/m²，且連續／restart 只在 LH 不同，其他欄位 bitwise 一致。
這不是合理的潛熱通量，也不能放寬容忍值使它通過。

因此只在乾 LES 的 runtime iofields 從 history 移除未定義的 `LH`，保留所有其餘欄位，
特別是 TKE、HFX、熱力與水物種。LES 的實際地表加熱由原始 `tke_heat_flux=0.24`
控制，與此未定義 LH 無關；核心、物理方案、網格及初始場不變。所有 tier 使用相同
輸出 schema，獨立重跑仍對全部已定義輸出做零容忍比較。
原始失敗證據保存於 `.wrf-cpu/runs/baseline-original-les/`。
診斷統計使用 float64，避免有限 float32 大值的加總本身溢位；真正 NaN/Inf 仍會失敗。

## CONUS restart 的初始 history

官方 `write_hist_at_0h_rst` 預設為 false。CONUS 的 `NOAHRES`、`U10E`、`V10E`
在 Registry 只有 history 標記，沒有 restart 儲存標記；重啟瞬間尚未重算，不能把它們
當成 checkpoint 內的預報狀態。我們最初強制寫 t=0 history，發現僅這三欄在初始點不同，
到首個整點後所有 207 個數值／重建欄位已 bitwise 一致。

CONUS 現恢復官方預設 `write_hist_at_0h_rst=false`，實際仍從第 6 小時完整積分至第 12 小時，
逐欄位比較第 7–12 小時共六筆完整輸出；不排除任何欄位，也不放寬數值門檻。四個理想
案例額外的 t=0 history 已可一致，保留該較強檢查。原始 CONUS restart 證據保存在
`.wrf-cpu/runs/baseline-original-conus12-restart/`，首小時比較報告在 `.wrf-cpu/progress/`。

## 三層 verify

1. `check` 要求 exit code=0、`SUCCESS COMPLETE WRF`、每個預定時間步都有 timing 記錄、
   精確歷史輸出時刻與網格、必要欄位齊全；掃描全部數值欄位 NaN/Inf 及 runtime fatal，
   並檢查異常負水物種。只讀到成功 log 不足以通過。
2. `compare` 讀 NetCDF 數值，比較所有輸出變數（含 U/V/W、熱力／壓力、啟用水物種、
   地表、降雨與診斷量），逐欄位逐時間報告 RMSE、max absolute error 與位置、bias、
   超標比例（`max_location` 是該欄位空間維度的零起算索引）；另由 P+PB、T+300、PH+PHB 重建完整氣壓、位溫、溫度與幾何高度。
3. 每個時間記錄降雨最大值、面積、質心、體積、負水物種比例、乾質量、水量、平均位溫
   與可用的 TKE／地表熱通量／輻射診斷，與 reference 一起報告。完整場一致也保留
   reference 的位置與結構。restart 尾段必須另外比較連續執行結果。

質量／水量／熱量診斷是 regression 指標，不能把開放區域的總量直接要求守恆，
也不能用這些比較宣稱已獨立證明全部科學正確性。若變更特定模組，應將其額外 tendency
或診斷欄位加入 runtime iofields 與 required list。

```bash
source perf/wrf_cpu/env.sh
python perf/wrf_cpu/verify.py check .wrf-cpu/runs/baseline/les/full --report /tmp/les-check.json
python perf/wrf_cpu/verify.py compare .wrf-cpu/runs/replay/les/full .wrf-cpu/runs/baseline/les/full --report /tmp/les-compare.json
python -m unittest discover -s perf/wrf_cpu -p 'test_*.py' -v
```

預設 bitwise（包含 signed zero），不比較整檔 hash 來判斷數值相同。
若因有根據的浮點順序改變需改用 tolerance，明確提供 `--policy policy.json`，格式為
`{"U":{"atol":0.000001,"rtol":0.000001}}`。未列出的變數仍是零容忍；水物種、近零降雨
等必須獨立決定符合單位與修改性質的門檻，不提供會自動放寬全部變數的預設值。

## 發布 golden 與後續候選版本

```bash
source perf/wrf_cpu/env.sh
python perf/wrf_cpu/publish.py --baseline baseline --replay replay
```

可在 baseline 執行中用 `python perf/wrf_cpu/watch.py <job-id>` 監測，僅在該工作成功後自動提交下列 finalize 工作。也可在 baseline 成功後，提交 `sbatch --output=.wrf-cpu/logs/finalize-%j.log perf/wrf_cpu/finalize.slurm`，於同一計算工作依序完成 replay、publish、audit 與實測摘要。

發布器重新讀取現有 NetCDF 檢查五案例的四種執行，重新確認獨立重跑與 restart
比較，確認輸入、namelist、ranks 與執行檔 provenance 一致後，才複製三種長度的
輸出到 `.wrf-cpu/golden/`。產物唯讀、附完整 SHA-256 manifest；已存在時拒絕覆蓋。
檔案 hash 僅用於封存完整性，數值 gate 仍由 NetCDF comparator 決定。候選執行前會自動核對 golden manifest seal、所有封存檔與固定輸入；也可單獨執行 `python perf/wrf_cpu/audit.py`。golden 發布後 baseline build 腳本拒絕覆寫既有建置。

後續候選版使用另一個 install 目錄與新的 label，不覆寫 baseline 執行檔：

```bash
sbatch --output=.wrf-cpu/logs/candidate-%j.log perf/wrf_cpu/run.slurm \
  --label candidate --against golden \
  --install-ideal /absolute/path/to/candidate-ideal \
  --install-real /absolute/path/to/candidate-real
```

每次 `run.json` 保存總 wall time、每步計算時間序列／mean／median、MPI ranks、CPU host、
Slurm job ID、輸入與執行檔雜湊；`check.json` / `compare.json` / `restart-compare.json`
保存驗證證據。性能比較需使用相同機型、ranks、輸出頻率及輸入，並另外考慮 I/O 與系統
負載；第一次 baseline 數據不代表統計顯著的加速比。
