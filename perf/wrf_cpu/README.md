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

每次 `run.json` 保存總 wall time、`Timing for main` 每步牆鐘時間序列／mean／median、MPI ranks、CPU host、
Slurm job ID、輸入與執行檔雜湊；`check.json` / `compare.json` / `restart-compare.json`
保存驗證證據。性能比較需使用相同機型、ranks、輸出頻率及輸入，並另外考慮 I/O 與系統
負載；第一次 baseline 數據不代表統計顯著的加速比。

目前 scaling／最佳化實驗記錄見 [EXPERIMENTS.md](EXPERIMENTS.md)。主要效能指標為完整 WRF
wall-clock seconds 除以驗證完成的 timestep 數。`Timing for main` 也涵蓋部分 I/O，並非純計算時間；
不能與另列的 I/O 時間相加。選定 ranks 後，獨立重跑與 restart 全部通過才能另封存 `scaled-golden`，
既有 `golden` 保留。`wrf_profile.py` 要求該封存參考存在，採樣執行不列入 speedup 證據。

`select_finalists.py` 先依完整 scaling 結果挑選候選設定，再以獨立重跑的中位數選出每個案例的
設定。`certify_scaled.py` 要求五個案例都有至少三次獨立完整執行及 bitwise 重跑證據，才會在
選定 ranks、domain decomposition 與 MPI placement 下重新執行 single／short／full／restart
及獨立 replay。理想化案例須使用單一節點，以保留 socket placement；CONUS 另配置所需節點。
全部 40 次驗證成功後才發布 `scaled-golden`，後續 5× 幾何平均的 baseline 採獨立重跑中位數。

Scaling 可用 `--discard-verified-output` 控制暫存用量：完成計時、執行檢查與全欄位比對後，
先將輸出檔名、大小及 SHA-256 寫入 `retired-outputs.json`，再清理可重建的 history／checkpoint
陣列；日誌、namelist、計時與完整比對報告保留。獨立重跑所需的第一份 history 會保留至最後一次
比對完成，canonical baseline／replay、golden 及失敗證據受保護。此清理不納入 WRF 計時，也不會
減少模擬中的輸出量。配額失敗與恢復紀錄見 `EXPERIMENTS.md` 的 S004a 段落。

相同 CPU 型號仍可能有不同 NUMA／快取拓撲。比較效能前，透過 `WRF_HARDWARE_REFERENCE`
指定已完成實驗的 `results.json`；scaling／certification 批次會先在每個配置節點執行
`hardware.py`，核對 CPU、核心／socket、NUMA CPU 分布、最高頻率及 L3 cache，任一差異即停止。
選擇 baseline 時也會拒絕同一案例混用不同硬體簽章。理想化案例採固定 2-NUMA 硬體，CONUS
採固定 8-NUMA 節點組；每個案例的 baseline、profiling 與最佳化測量都必須使用對應硬體。
初輪 NUMA 差異的診斷與重新量測見 `EXPERIMENTS.md` 的 H001／S003q 紀錄。
後續 `certify_scaled.py`／`wrf_profile.py` 也會直接由選定／封存參考讀取硬體簽章並逐節點檢查，
不依賴呼叫者設定額外環境變數。新 `run.json` 保存靜態硬體簽章，發布參考時 baseline 與 replay
必須一致；這些檢查都在 WRF 計時之外。

## 目前正式比較基準與已通過候選

目前 baseline 採 S005m 獨立確認的原始版本最佳設定，每案至少三次完整執行的中位數；
候選與 baseline 都以完整 wall-clock seconds / verified timestep 計算，包含啟動、初始化、
原定 history 與兩份 checkpoint。每個案例的原始節點、核心預算與硬體簽章固定。

| 案例 | baseline MPI ranks | baseline s/timestep | C021 s/timestep | speedup |
|---|---:|---:|---:|---:|
| b_wave | 32 | 0.023615 | 0.013732 | 1.720× |
| quarter_ss | 16 | 0.023853 | 0.015471 | 1.542× |
| les | 16 | 0.009725 | 0.006945 | 1.400× |
| convrad | 80 | 0.030367 | 0.018876 | 1.609× |
| conus12 | 840 | 0.430314 | 0.182201 | 2.362× |

2026-11-09：B024模型／ISA-L加上SIMD shuffle之相同C021 payload已通過五案
single／short／full／restart、每案三次完整計時及原始數值、格式、核心綁定檢查。
正式幾何平均為 **1.697812×**，5× 目標尚未達成。
CONUS12三次完整耗時為109.756126、109.284231、109.320889秒，中位數109.320889秒；
理想四案作業2030045、CONUS作業2030070及獨立稽核／重算作業2030149均成功完成。
維持原始REAL4、物理、輸出頻率、兩份checkpoint及NetCDF4壓縮等級2。
正式證據是 `.wrf-cpu/experiments/C021-shuffle-locality/summary.json`，
固定reference manifest SHA為`2582bb6e358acddad8cc709faf5d194b196945d400f7238b646cca45812e3772`。
先前C011＋C015的1.683226×與C005的1.180476×原紀錄仍保留；各次完整同payload成績分開計算。

完整CONUS profiling P010（作業2029805）亦成功完成原600步、13份history、兩份checkpoint及原始／候選restart驗證。
取樣rank0/210/420/839均無遺失樣本；rank0的copy4、memmove、HDF5 shuffle分別佔self CPU樣本10.21%、6.56%、4.69%。
其他取樣rank有大量MPI broadcast等待；這些是CPU樣本占比，不能當作wall time比例或可消除的成本。
報告為 `.wrf-cpu/experiments/C016-current-conus-full-profile-r01-p840/analysis.json`，profiling時間不計分。
文獻條件、適用性與後續實驗取捨見 [PAPER_REVIEW.md](PAPER_REVIEW.md)；
完整實驗紀錄見 [EXPERIMENTS.md](EXPERIMENTS.md)。
文獻導向補測：M028 convrad反向MPI排列10×8在首步有38項bitwise比較不符，維持8×10；
M029以目前HDF5濾鏡為基準的shuffle元件通過26,112組檢查，六種chunk元件加速幾何平均4.500413×。
M029是元件結果；後續B027／C021管線與完整模型驗證見下節，元件倍率不直接計入正式五案表。

## Shuffle 候選 C021：管線與完整五案已驗證

B027已將M029 kernel接入目前HDF5。72個NetCDF變數可由原庫／候選庫交叉讀回，
raw bits、schema、chunks與filters一致；163個實際儲存的壓縮chunk bytes也完全相同。
C021保留原B024模型與ISA-L，僅加入此shuffle adapter；五案各三次完整計時及原始single／short／restart均通過。
獨立稽核涵蓋30階段的數值、格式、所有rank綁定、實際後端與成功輸出退役證據，7份raw差異LES LH checkpoint保留。

| 案例 | C021 full中位秒 | 相對固定原始baseline加速 |
|---|---:|---:|
| b_wave | 9.886754 | 1.719766× |
| quarter_ss | 4.641248 | 1.541837× |
| les | 25.002475 | 1.400317× |
| convrad | 13.590869 | 1.608719× |
| conus12 | 109.320889 | 2.361746× |

相對C011舊候選，convrad／quarter_ss觀察到約1.33%／0.49%改善，LES／b_wave則約慢0.21%／0.37%。
CONUS相對前候選觀察到3.129%改善，五案正式幾何平均相對前候選增加0.867%。
這些是不同完整驗證群組的觀察值，尚未建立相對舊候選的穩定通用收益，也未進行新的配對統計推論。
CONUS作業2030070實際在10:34:25開始、18:07後成功完成，早於先前可變的17:52預估；
既有監看程序接續提交2030149，六秒完成獨立real稽核與原scorer重算，沒有取消／重排模型。
目前正式總分為上節C021的1.697812×，沒有混用舊候選的各案最快值。

可重現原始碼為 [fast_shuffle4.c](fast_shuffle4.c) 與 [fast_shuffle4.map](fast_shuffle4.map)。
獨立C檔和實測B027 adapter＋kernel的預處理translation unit逐byte相同，證據在
`.wrf-cpu/experiments/B027-shuffle-adapter/canonical-source-audit.json`。
此候選使用目前固定HDF5的私有descriptor符號；執行時保留原descriptor參數callback與讀取路徑，
只有4byte寫入重排使用已檢查的SSE4.1，其他大小／小buffer／reverse仍使用原函式。
它未設為預設執行政策；使用時需保留已驗證的HDF5 ABI與payload鎖定。

在compute allocation中，以現有env及同一設定建置到新的輸出路徑：

```bash
source perf/wrf_cpu/env.sh
shuffle_prefix="$PWD/.wrf-cpu/env"
shuffle_output="$PWD/.wrf-cpu/experiments/B027-shuffle-adapter/canonical-shuffle.so"
test ! -e "$shuffle_output"
gcc -std=c11 -Wall -Wextra -Werror -O3 -g -fPIC -shared \
  -I"$shuffle_prefix/include" perf/wrf_cpu/fast_shuffle4.c \
  -L"$shuffle_prefix/lib" -Wl,--no-as-needed -lhdf5 -Wl,--as-needed \
  -Wl,-rpath,"$shuffle_prefix/lib" \
  -Wl,--version-script=perf/wrf_cpu/fast_shuffle4.map -Wl,-z,defs -ldl \
  -o "$shuffle_output"
```

實際驗證候選使用B027封存的`shuffle.so`，SHA為
`9bbd82012696389b84e11dbba33a89269b86bb3254ea3237998f0821273a9938`；
重建後的binary仍需重新檢查相容性與payload，不能直接替換已驗證的執行檔。
完整原始紀錄與成功／失敗輸出政策見 [EXPERIMENTS.md](EXPERIMENTS.md)。


## 候選推進歷程與可重現壓縮器來源

以下C006至C012敘述保留各階段當時的結果；最新正式成績以上節C021為準。

C006（B021 native128）四個 ideal 案例已各通過 single／short／full／restart 與三次完整計時：

| 案例 | C006 s/timestep | speedup |
|---|---:|---:|
| b_wave | 0.016565 | 1.426× |
| quarter_ss | 0.016980 | 1.405× |
| les | 0.007070 | 1.376× |
| convrad | 0.022436 | 1.353× |

C006 的 CONUS12 short 在十步後有56個變數時間／衍生量比較項目不一致，因此不能建立新的五案正式總分。
C007（B022）僅恢復 Thompson 原始 GNU O2／x86-64 編譯方式，CONUS12 single 與 short 位元一致；
full 尚未開始，因保守 quota 可用容量低於14.6GB門檻而停止。後續 D021 診斷雖跑完600步，卻出現後半段 HDF 輸出失敗，仍不合格；D023 僅確認前七份可讀歷史場（0–6小時）位元一致。這些結果不能取代上節 C005 五案正式成績，
也不能混用不同候選的各案最快值計算正式幾何平均。完整紀錄見 [EXPERIMENTS.md](EXPERIMENTS.md)。

[fast_compress2.c](fast_compress2.c) 與 [fast_compress2.map](fast_compress2.map) 是已驗證 B004 的原始來源，
只匯出 compress2，以 libdeflate 無損產生 zlib 串流；其他 zlib API 保留原庫，不改變 NetCDF4、shuffle 或壓縮等級2。
版本固定 libdeflate 1.26，來源 https://codeload.github.com/ebiggers/libdeflate/tar.gz/refs/tags/v1.26，tar SHA256 `bba03fffc5538576213675ce6968fcff6ce2e67d82e4d5febea2d05f9f13cf85`。
先在 compute allocation 依上游 CMake 建置 PIC static library，開啟並通過上游測試；
假設 LIBDEFLATE_SOURCE、LIBDEFLATE_BUILD 指向已核對的來源與建置目錄：

```bash
source perf/wrf_cpu/env.sh
cmake -S "$LIBDEFLATE_SOURCE" -B "$LIBDEFLATE_BUILD" -G Ninja \
  -DCMAKE_C_COMPILER=gcc -DCMAKE_BUILD_TYPE=Release -DCMAKE_POSITION_INDEPENDENT_CODE=ON \
  -DCMAKE_PREFIX_PATH="$NETCDF" -DLIBDEFLATE_BUILD_STATIC_LIB=ON \
  -DLIBDEFLATE_BUILD_SHARED_LIB=OFF -DLIBDEFLATE_BUILD_TESTS=ON
cmake --build "$LIBDEFLATE_BUILD" --parallel 8
ctest --test-dir "$LIBDEFLATE_BUILD" --output-on-failure
gcc -O3 -std=c11 -fPIC -shared perf/wrf_cpu/fast_compress2.c "$LIBDEFLATE_BUILD/libdeflate.a" \
  -I"$LIBDEFLATE_SOURCE" -I"$NETCDF/include" -pthread -ldl \
  -Wl,--version-script=perf/wrf_cpu/fast_compress2.map -o /tmp/fast-compress2.so
python perf/wrf_cpu/check_fast_compress2.py --library /tmp/fast-compress2.so \
  --report /tmp/fast-compress2-compatibility.json
```

相容性檢查包含真實原始 CONUS T／P／U／QRAIN shuffle chunks，所有 decoded bytes 必須完全相同；
壓縮微測資的成績不等同完整 WRF 加速。正式候選仍須獨立通過五案、三次 full 與 restart 的全部檢查。

硬體稽核逐一向實際配置的每個節點取得完整報告，由主節點統一寫入；節點數、job、reference雜湊與CPU／NUMA簽章都必須相符。這只減少計時外的寫入端，不代表模型輸出容量已足夠。`open_hist_w` 寫入開啟失敗即拒絕執行結果，exit0或`SUCCESS COMPLETE WRF`不能覆蓋I/O失敗。


[isal_compress2.c](isal_compress2.c) 保存 B023 已實測的 ISA-L adapter 原始碼；使用同一份
[fast_compress2.map](fast_compress2.map) 限制匯出符號。ISA-L 固定2.32.1，官方來源
https://github.com/intel/isa-l/archive/refs/tags/v2.32.1.tar.gz，tar SHA256
`d9f7179ab0e14a3db9b610fac22793854a1435e8423ec9ce07f4cbedc5f92f5e`。
B023 的231項相容性、12項並行檢查與三項相關上游測試通過；D024 的原始 CONUS10步、414項位元比較及
實際 NetCDF4 deflate2 設定也通過。這是尚待完整五案驗證的候選壓縮器，C005 的正式成績不變。
只對 compress2(level=2) 使用 ISA-L level2 zlib wrapper；其餘等級及容量／配置失敗回到原始 zlib。
B023 真實 chunks 的壓縮時間比既有 libdeflate 快4.30–6.26倍，壓縮大小增加約1.8–9.0%；不能直接換算為 WRF 加速。

先核對並解開官方 tar，令 WRF_ISAL_SOURCE、WRF_ISAL_BUILD 指向獨立來源及建置目錄，再於 compute allocation 執行：

```bash
source perf/wrf_cpu/env.sh
cmake -S "$WRF_ISAL_SOURCE" -B "$WRF_ISAL_BUILD" -G Ninja \
  -DCMAKE_C_COMPILER=gcc -DCMAKE_BUILD_TYPE=Release -DCMAKE_POSITION_INDEPENDENT_CODE=ON \
  -DBUILD_SHARED_LIBS=OFF -DISAL_BUILD_TESTS=ON -DISAL_BUILD_PERF_TESTS=OFF \
  -DISAL_BUILD_ISAL_SHIM=OFF -DCMAKE_PREFIX_PATH="$NETCDF"
cmake --build "$WRF_ISAL_BUILD" --parallel 8
ctest --test-dir "$WRF_ISAL_BUILD" --output-on-failure \
  -R '^(igzip_rand_test|igzip_wrapper_hdr_test|checksum32_funcs_test)$'
gcc -O3 -std=c11 -Wall -Wextra -Werror -fPIC -shared perf/wrf_cpu/isal_compress2.c \
  "$WRF_ISAL_BUILD/libisal.a" -I"$WRF_ISAL_SOURCE/include" -I"$NETCDF/include" \
  -pthread -ldl -Wl,--version-script=perf/wrf_cpu/fast_compress2.map -o /tmp/isal-compress2.so
python perf/wrf_cpu/check_fast_compress2.py --library /tmp/isal-compress2.so --backend-name isal \
  --input "$WRF_CPU_ARTIFACTS/scaled-golden/conus12/full/wrfout_d01_2019-11-26_21:00:00" \
  --report /tmp/isal-compress2-compatibility.json
```

`candidate_run.py --retain-outputs` 保留全部驗證後的科學輸出，並將此政策寫入結果；C008／C009 的診斷額外禁止呼叫任何退役函式。
每次候選仍必須使用獨立名稱，保留失敗紀錄，不得以壓縮元件或短測試替代完整模型與 restart。


D026 以同一個原始執行檔的 S006 baseline／獨立 replay 實證：乾 LES 兩個 checkpoint
皆只有未定義的 `LH` 位元不同，其餘變數相同。封存 manifest 的原始數值比較範圍為全部 history／
重建量與 restart 軌跡；LH 僅移出 history，仍完整寫入 checkpoint。後續候選保留此原始比較範圍，
額外 raw checkpoint 報告會明列 LES LH 的失敗，不宣稱完整 checkpoint 全位元相同；其他 raw checkpoint
欄位、schema 與 filter 差異仍會阻擋診斷。C009 convrad 三次 full 中位14.072秒、相對固定基準1.554倍，
已通過含完整 checkpoint 的各層檢查；C010 四案各三次 full 與原始 single／short／restart 已通過，不計入五案正式總分。

C010（同一 B022 模型加 ISA-L）已通過四案24次原始科學驗證並保留193份輸出：

| 案例 | full 中位秒 | 相對固定 baseline 加速 |
|---|---:|---:|
| b_wave | 10.296 | 1.651× |
| quarter_ss | 4.743 | 1.509× |
| les | 24.947 | 1.403× |
| convrad | 14.138 | 1.546× |

截至C010階段，CONUS12尚缺同版本full／restart／三次完整計時，當時五案正式幾何平均仍為C005的1.1805倍。


## I/O 拷貝候選 C011 與後續 real 驗證

B024 僅加快 patch 拼接與 NetCDF 單word轉置，保留所有算術、格式、欄位與輸出工作。
980項原型檢查與1240項整合／舊路徑檢查通過；精度轉換函式可執行碼未改變。
C011四組ideal均完成原始single／short／full／restart與三次full，保留193份輸出：

| 案例 | full中位秒 | 相對固定baseline加速 |
|---|---:|---:|
| b_wave | 9.850 | 1.726× |
| quarter_ss | 4.664 | 1.534× |
| les | 24.950 | 1.403× |
| convrad | 13.772 | 1.588× |

LES與C010相當；其原始未定義LH checkpoint差異仍獨立列報，其餘欄位保持原始比較。
CONUS12單步／短程也通過，短程17.919秒僅為診斷；full因可用3.750GB低於原門檻14.600GB而未啟動。
這是C011當時未能建立五案新總分的原因；後續相同payload的C015已完整通過，最新結果見上節。

容量選項與精確唯讀盤點位於工作區
.wrf-cpu/progress/space-recovery-proposal-v2-20261107.md 與
.wrf-cpu/experiments/M017-capacity-review/inventory.json。
使用者已明確核可方案 B；M018 作業2024492完成27項來源封存檔硬連結合併、168份精確成功輸出退役與5個舊建置目錄清理。
保留來源路徑與內容、所有失敗／中止輸出、既有C011資料、6份raw差異checkpoint及原始參考；逐檔SHA與操作journal可稽核。
清理後當次保守可用量16.538GB，後續啟動仍重新檢查原14.6GB full／7.1GB restart門檻。
C012使用C011相同payload與provenance另建CONUS12群組，執行原始完整流程；僅退役核可後新建且所有驗證已通過、已無restart依賴的科學檔案。


方案B後的實測：C012第一輪CONUS12 full完成600步／13份history／兩份checkpoint，
2691項原始bitwise比較與兩份raw checkpoint均通過，單次耗時113.577秒。
隨後restart雖完成300步，最後history與checkpoint讀回發生HDF錯誤，整組驗證失敗；
因此沒有三次full中位數，也不更新五組正式分數。失敗資料與第一輪full均保留。
事後檢查確認前5份restart history的1035項比較一致，最後checkpoint僅3695bytes且HDF metadata不完整；
容量壓力與現象相符，但未取得原始寫入errno，不能認定唯一原因。

P009已完成目前版本四組ideal的full profiling與原始／候選restart比對，
16個取樣rank均有足夠樣本、零遺失；profiling耗時不計分。
目前copy4、memmove與動力計算仍值得進一步量測。報告位於
.wrf-cpu/experiments/P009-current-ideal-profile-setup/analysis.json。
新成功輸出已依核可政策留存SHA／proof journal後退役，raw差異checkpoint保留。
當時實際用量即使不計預留，也只剩約11.93GB，低於原14.6GB full門檻。
容量恢復後C015已成功完成；這個歷史容量讀數不代表目前剩餘容量。

已補做單執行緒 tiling 控制實驗 M020：固定目前B024／ISA-L、MPI配置與1執行緒，
四組ideal各測8種設定。可通過全部原始比對的Y向切分在LES、convrad、quarter_ss均較慢；
b_wave經控制組與候選各3次全新full交錯比較，中位數9.8495秒對9.8661秒，兩個Y向tile亦無收益。
20組X向切分在單步就不符合原始bitwise比較，失敗資料保留。
因此仍採tile_sz_x/y=0、numtiles=1；沒有新增通用tiling設定功能。
M020作業2029433完成，原CONUS12驗證已用相同腳本重新排為C015作業2029537；
取消的舊待排項目2029417沒有執行模型，不能作為計分證據。
