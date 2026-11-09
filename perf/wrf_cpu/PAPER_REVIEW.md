# WRF 最佳化文獻與本專案實驗對照

核對日期：2026-11-09。以下區分原文結果與本專案判斷。
本專案正式口徑為三次完整執行wall-clock秒數中位數／已驗證步數，包含啟動、初始化、history、兩份checkpoint與結束寫入。
固定CPU／節點預算、物理、REAL4、輸出與NetCDF4壓縮等級2；原始定義欄位要求bitwise一致，並驗證原始／候選restart。
最新同payload五案正式幾何平均1.683226×，尚未達5×；論文倍率不納入本專案成績。

## 六篇來源的條件與適用性

| 原始來源 | 原文結果與比較條件 | 對本專案的判斷 |
|---|---|---|
| Huang等，[Performance Evaluation and Optimization…Based on Kunpeng 920](https://www.mdpi.com/2076-3417/13/17/9800)，2023，DOI 10.3390/app13179800 | ARM平台結合Libamath、domain decomposition與tiling，單步0.92→0.62秒，時間減少32.6%，比值約1.484×。單步統計為最後10步平均，刻意排除I/O。另有異步I/O整體1078.80→807.94秒結果。 | 參考cache、MPI／OpenMP與I/O調校方法。ARM數學庫不適用本機Xeon；替換數學函式須重新證明bitwise一致。單步降幅、單次寫入改善不能取代完整wall-clock。原文tiling設定敘述存在不一致，不能直接照抄數值。 |
| Elliott等，[WRF Performance Optimization Targeting Intel Multicore and Manycore Architectures](https://ams.confex.com/ams/96Annual/webprogram/Paper284190.html)，AMS 2016摘要 | WRF3.7、Stampede Xeon E5-2660／Xeon Phi；改善OpenMP tile負載不均，報告10–20%加速。最佳設定依網格、MPI切分與threads/task而變。可讀來源是會議摘要。 | M020已隔離OMP=1的serial tiling，不能視作完整重現論文的hybrid thread負載平衡。D003的OMP=3結果同時改變編譯／配置，也不能拿來單獨證明tiling效果。後續hybrid測試需固定總核心與實際binding。 |
| Moreno等，[Analysis of a New MPI Process Distribution…](https://onlinelibrary.wiley.com/doi/10.1155/2020/8148373)，2020，DOI 10.1155/2020/8148373 | WRF3.9.1、Xeon E5450／Intel工具鏈；比較各因數排列，在通訊與cache間取捨，提出平台調校的分解規則。不是所有網格都以近方形最佳。 | 補查現有rank數的合法排列，不直接套用論文平台的參數。M027依實際啟動檢查列舉合法配置，見下節；仍須原始科學驗證與完整交錯確認。 |
| Malakar等，[A Divide and Conquer Strategy for Scaling Weather Simulations with Multiple Regions of Interest](https://cds.iisc.ac.in/faculty/vss/publications/preeti-divideconquer-sc2012.pdf)，SC12 | IBM Blue Gene，多個巢狀兄弟domain並行、處理器配置及torus拓樸映射；報告integration-step時間最多減少約33%，拓樸映射另改善最多約7%。 | 現有五案均為單domain，沒有可並行的兄弟巢狀網格。處理器配置與拓樸觀念可參考，但新增巢狀domain會改變工作負載，這次不採用。 |
| Ouermi等，[Performance Optimization Strategies for WRF Physics Schemes Used in Weather Modeling](https://www.jstage.jst.go.jp/article/ijnc/8/2/8_301/_article/-char/en)，2018，DOI 10.15803/ijnc.8.2_301 | NEPTUNE使用的WSM6／GFS physics與radiation核心，採thread-local SoA、OpenMP SIMD與記憶體配置調整；大倍率包含與原始serial核心比較，並非整個WRF的加速比。 | convrad的P009中WSM6佔rank0 self CPU約5.38%，可作為資料區域性研究對象。需先證明陣列相依性與運算順序，不能以核心倍率估算全模型，更不能更換CONUS物理。M021已證明單純加寬advance_uv向量在本機反而較慢。 |
| Wichitrnithed等，[Optimizing the Weather Research and Forecasting Model with OpenMP Offload and Codee](https://conferences.computer.org/sc-wpub/pdfs/SC-W2024-6oZmigAQfgJ1GhPL0yE3pS/555400b934/555400b934.pdf)，SC24 WACCPD | WRF4.5.2／NVHPC／Perlmutter A100，FSBM微物理；CONUS425×300×50、dt5秒、模擬10分鐘。TableVII在16ranks＋16GPUs為1211.45→581.2秒，2.08×；驗證段記錄仍有數值差異。 | 本案CONUS為Thompson、CPU、dt72秒／12小時，並要求bitwise一致。借用profile→相依性分析→減少資料搬移流程；此GPU／物理配置與精度驗證不能直接移用為本案加速。 |

## 對照目前完整 profile

P009完整四案與P010完整CONUS皆通過原始／候選restart；取樣時間不計分。
P010 rank0 self CPU為copy4 10.21%、memmove 6.56%、ISA-L deflate主要迴圈5.17%、HDF5 shuffle 4.69%、NetCDF transpose 2.73%。
其他三個取樣rank的HCOLL broadcast progress約47–49%，可能包含等待root資料／I/O的時間，不能推定停用HCOLL便能消除這些成本。
M026實測yield政策也沒有穩定通用改善。這些占比不是全模型wall-time比例，不能直接代入Amdahl公式作精確預測。

因此接下來優先檢查可減少資料搬移的具體路徑，並以合法MPI排列作小範圍控制實驗。
廣泛增加SIMD寬度、copy loop unroll與serial tiling已分別被M021、M023／M025、M020否決，沒有新證據時不重跑。
獨立IPO／LTO建置B025僅是待驗證的編譯候選，原始Thompson編譯與禁止FMA條件仍需保留；不假定它能帶來5×。

已依資料區域性方向完成M029 shuffle元件測試：使用目前實際HDF5 builtin filter為控制組，
以128bit整數指令重排4byte元素，其他大小、參數與反向操作沿用原函式。
ASAN／UBSAN與O3兩種模式合計26,112組位元、反轉、特殊浮點位元及未對齊／哨兵檢查通過。
六種chunk大小各五次交錯量測，加速4.344–4.770×，元件幾何平均4.500413×；
正式CONUS T／P／QRAIN與U chunk的6,232,800／6,262,200bytes分別為4.348845／4.344041×。
這證明此資料搬移路徑值得整合測試；尚未替換HDF5登錄或執行完整WRF，不能當作整體4.5×。
原始碼、raw計時、sanitizer、實際SSE指令、原HDF5連結與獨立重算證據在
`.wrf-cpu/experiments/M029-shuffle-locality/`。

## M027：固定 ranks 的合法分解盤點

本版 `share/module_check_a_mundo.F` 以整數除法檢查 `e_we/nproc_x >= 10` 且 `e_sn/nproc_y >= 10`。
唯讀列舉所有因數排列，結果如下；通過啟動限制不代表數值或性能已通過。

| 案例 | 固定ranks | 合法nproc_x×nproc_y | 已知比較 |
|---|---:|---|---|
| b_wave | 32 | 4×8 | 唯一合法排列 |
| quarter_ss | 16 | 4×4 | 唯一合法排列 |
| les | 16 | 4×4 | 唯一合法排列 |
| convrad | 80 | 8×10、10×8 | M028已補測：8×10通過原四層驗證；10×8單步有38項bitwise比較不符，拒絕採用 |
| conus12 | 840 | 28×30、30×28、35×24、40×21、42×20 | 原版scaling已比較28×30與35×24；當時中位258.188與263.801秒，不代表當前B024亦有相同排序 |

盤點的程式版本、來源SHA、所有合法／不合法因數對與判定規則保留於
`.wrf-cpu/experiments/M027-paper-guided-grid-review/analysis.json`。
沒有修改最小patch限制、降低基準分母、重算物理或新增測資。
M028作業2029986已成功完成控制流程；新排列未通過數值門檻，沒有合格加速比，失敗資料保留。
