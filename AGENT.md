# 專案工作規範

## 實驗紀錄

每次做實驗都必須留下紀錄，包含實驗目的、程式版本、環境與設定、執行指令、結果及結論，並註明相關輸出或報告的位置。失敗或中止的實驗也必須記錄。

## Commit title 格式

每次 commit 的 title 必須使用以下格式：

```text
<type>: <description>
```

`type` 僅限 `feat`、`fix`、`perf`、`bench`、`chore`、`refactor`、`docs`；冒號後須有一個空格，`description` 須簡潔描述本次變更。

例如：

```text
bench: add WRF CPU baseline validation workflow
docs: document experiment logging requirements
```
