# 台灣國際航班時刻表（含航廈）

`tdx_flights.py` 從 [TDX 運輸資料流通服務](https://tdx.transportdata.tw/) 抓取所有進出台灣機場的國際定期航班表，展開成未來 N 天（預設 60 天）的每日航班，並為每個航班號補上航廈資訊。

只使用 Python 標準函式庫，不需安裝任何套件（Python 3.7+）。

## 資料來源

| 來源 | 用途 |
| --- | --- |
| TDX `Air/GeneralSchedule/International` | 國際定期航班表（航班號、起訖機場、時間、星期、有效期間、共掛班號） |
| 桃園機場 `a_flight_v4.txt` | 桃園機場官方近 3 天航班檔（Big5），用來推算 TPE 航班的航廈 |

## 執行方式

### 1. 取得 TDX API 金鑰

到 TDX 註冊會員，在「會員中心 → API 金鑰」取得 `Client Id` 與 `Client Secret`。

### 2. 線上抓取（預設）

```bash
export TDX_CLIENT_ID=你的ClientId
export TDX_CLIENT_SECRET=你的ClientSecret

python3 -I tdx_flights.py out            # CSV 輸出到 data/，暫存檔放 out/，涵蓋今天起 60 天
python3 -I tdx_flights.py out --days 30  # 改為 30 天
```

會自動下載桃園機場的 `a_flight_v4.txt`，並把 TDX 原始回應存成 `out/tdx_schedule_raw.json`，方便之後離線重跑。

### 3. 離線重跑（不需金鑰）

```bash
# 重用先前存下的 TDX 回應（仍會重新下載桃園航班檔）
python3 -I tdx_flights.py out --from-json out/tdx_schedule_raw.json

# 完全離線：連桃園航班檔也用本機檔案
python3 -I tdx_flights.py out --from-json out/tdx_schedule_raw.json --tpe-file out/a_flight_v4.txt
```

### 參數

| 參數 | 說明 |
| --- | --- |
| `OUT_DIR` | 暫存目錄，放 TDX 原始回應與桃園航班檔（必填，不存在會自動建立） |
| `--days N` | 展開的天數，預設 `60` |
| `--from-json PATH` | 使用本機的 TDX 回應 JSON，不呼叫 TDX API |
| `--tpe-file PATH` | 使用本機的 `a_flight_v4.txt`，不重新下載 |
| `--data-dir PATH` | CSV 輸出目錄，預設 `data`（不存在會自動建立） |

> `-I`（isolated mode）可避免讀到目前目錄或 `PYTHON*` 環境變數中的程式碼，非必要但建議使用；`TDX_*` 環境變數不受影響。

## 輸出檔案

CSV 寫到 `--data-dir`（預設 `data/`），暫存檔寫到 `OUT_DIR`。所有 CSV 皆為 UTF-8 with BOM，可直接用 Excel 開啟。

| 檔案 | 內容 |
| --- | --- |
| `tw_intl_flights_by_schedule.csv` | 每筆航班表一列：航班號、起訖、時間、飛行星期、有效期間、航廈與其來源、共掛班號 |
| `tw_intl_flights_daily.csv` | 展開後的每日航班，一天一班一列；共掛班號也各自一列，`operating_flight` 填實際執飛班號 |
| `tw_intl_flight_terminal_lookup.csv` | 航班號 + 方向 → 航廈 對照表；期間內航廈有變動者 `terminal_changes` 標 `Y` |
| `tdx_schedule_raw.json` | TDX 原始回應（僅線上模式產生） |
| `a_flight_v4.txt` | 桃園機場航班檔（未指定 `--tpe-file` 時下載） |

執行結束會在終端機印出統計：航班表筆數、每日航班數、各 `terminal_source` 的數量，以及無法判定航廈的航班清單。

## 處理邏輯

1. **篩選國際段**：起訖機場恰有一端在台灣（TPE、TSA、KHH、RMQ、TNN…）才保留，並判定為「出境」或「入境」；同時去除 TDX 中完全重複的紀錄。
2. **展開日期**：依 `ScheduleStartDate`～`ScheduleEndDate` 與星期欄位展開成實際日期。TDX 的星期與日期以「出發日」為準，因此會往前多看 2 天，以涵蓋 `+1`/`+2` 跨日抵台的班機；最後以**台灣端日期**（出境看出發日、入境看抵達日）`tw_date` 篩選在 `[今天, 今天+N]` 內。
3. **航班號正規化**：統一成 `航空公司代碼 + 去前導零數字`，例如 `CI 0005` → `CI5`。
4. **判定航廈**，依序嘗試，結果記錄在 `terminal_source`：

   | 值 | 判定方式 |
   | --- | --- |
   | `tdx` | TDX 紀錄本身帶有航廈欄位 |
   | `fixed` | 非桃園機場且只有單一國際航廈（松山、高雄、台中等） |
   | `tpe_exact` | 桃園航班檔中有相同航班號與方向 |
   | `tpe_route` | 桃園航班檔中同航空公司、同外站只出現在一個航廈 |
   | `tpe_airline` | 桃園航班檔中該航空公司只在一個航廈營運 |
   | `unknown` | 無法判定 |

   桃園航班檔只涵蓋近 3 天，因此較遠日期的新航班可能落到 `tpe_route` / `tpe_airline` 或 `unknown`。

## License

程式碼以 [MIT License](LICENSE) 授權。

輸出的航班資料來自 TDX 運輸資料流通服務與桃園國際機場，其使用須遵守各來源的授權條款（TDX 依[政府資料開放授權條款](https://data.gov.tw/license)），不在本專案 MIT 授權範圍內。
