# Pocket F9P - GNSS RTK over BLE

## プロジェクト概要

XIAO ESP32C3上のMicroPythonで動作する、u-blox F9P GNSS受信機とスマートフォンをBLE接続するファームウェアです。

### 機能
- F9PからのNMEAデータをBLE経由でスマートフォンに送信
- スマートフォンからのRTCM補正データをF9Pに転送
- 自動ボーレート検出（9600/38400/115200/57600/19200/230400 bps）
- UBXバイナリプロトコルのフィルタリング（NMEAのみをスマホに送信）

## ハードウェア構成

### 接続
```
F9P UART1          XIAO ESP32C3
---------------------------------
TX1        →       D1 (GPIO2, RX)
RX1        ←       D2 (GPIO3, TX)
GND        -       GND
```

### 検出されたボーレート
- **115200 bps** (NMEA + UBX混在出力)

## 問題解決の記録

### 初期問題
**症状**: F9Pからのデータを受信できない（ボーレート設定は正しいはずだが1バイトしか受信できない）

### 原因と解決策

#### 1. 配線の問題
- **原因**: TX/RXピンが逆に接続されていた
- **解決**: 正しい配線に修正
  - F9P TX → XIAO D1 (GPIO2, RX)
  - F9P RX → XIAO D2 (GPIO3, TX)

#### 2. ボーレート不一致
- **原因**: u-centerで38400bpsに設定したつもりが、実際は115200bpsで動作していた
- **解決**: 複数のボーレートを自動検出する機能を実装
  - 各ボーレートで2秒間（500ms × 4回）データを待機
  - データ内容を検証（NMEA `$` または UBX `0xB5 0x62`）
  - 印字可能文字の割合をチェック

#### 3. UBX/NMEA混在データ
- **原因**: F9PがUBXバイナリ（95%）とNMEA（5%）を混在出力
- **解決**: NMEAフィルタリング機能を実装
  - UBXメッセージ（`0xB5 0x62`）を検出してスキップ
  - NMEAセンテンス（`$`で始まる）のみを抽出

#### 4. NMEA誤検出
- **原因**: UBXバイナリデータ中に偶然`0x24` (`$`)が含まれ、NMEAと誤認識
- **解決**: 厳格なNMEA検証ロジックを実装
  - `$`で始まる
  - 次の5文字が大文字アルファベットまたは数字（例：GNRMC, GNGGA）
  - 6番目の文字がカンマ`,`

## 実装した機能

### 1. ボーレート自動検出 (`detect_baudrate()`)
```python
def detect_baudrate():
    """Detect F9P baudrate by trying common rates"""
    for baudrate in [9600, 38400, 115200, 57600, 19200, 230400]:
        # 2秒間データを監視
        # NMEA ($) または UBX (0xB5 0x62) マーカーを検出
        # 印字可能文字の割合をチェック
```

**特徴**:
- 複数のボーレートを順番に試行
- データの内容を検証（プロトコルマーカーと印字可能文字率）
- UBXバイナリにも対応（印字可能文字が少なくても許容）

### 2. NMEA検証 (`is_valid_nmea_start()`)
```python
def is_valid_nmea_start(data, start_pos):
    """Check if position in data is a valid NMEA sentence start"""
    # $GPXXX, または $GNXXX, の形式を検証
    # - '$' で始まる
    # - 次の5文字が [A-Z0-9]
    # - 6文字目が ','
```

**効果**:
- UBXバイナリ中の偶然の`0x24`を誤検出しない
- 正しいNMEAセンテンスのみを抽出

### 3. UBX/NMEAフィルタリング
```python
# メインループでF9Pからのデータを処理
while True:
    if uart.any() > 0:
        f9p_data = uart.read(uart.any())

        # UBXメッセージをスキップ
        if data[i] == 0xB5 and data[i+1] == 0x62:
            # ペイロード長を読み取り、メッセージ全体をスキップ

        # NMEAセンテンスを抽出
        elif data[i] == 0x24 and is_valid_nmea_start(data, i):
            # 改行まで読み取り、BLEに転送
```

**効果**:
- スマホアプリはNMEAデータのみを受信
- 不要なUBXデータは転送しない

### 4. BLE Nordic UART Service (NUS)
- Service UUID: `6E400001-B5A3-F393-E0A9-E50E24DCCA9E`
- TX Characteristic: `6E400003-...` (Notify)
- RX Characteristic: `6E400002-...` (Write)

## 動作確認ログ

### 起動時
```
Detecting F9P baudrate...
Trying baudrate: 115200...
  -> Found NMEA+UBX data!
Detected GNSS data at baudrate: 115200
Using baudrate: 115200
```

### BLE接続後
```
BLE Connected
Read 346 bytes from F9P, forwarding 265 bytes NMEA to BLE
Sent 265 bytes to BLE
Read 237 bytes from F9P (UBX only, not forwarding)
Read 389 bytes from F9P, forwarding 105 bytes NMEA to BLE
Sent 105 bytes to BLE
```

### データ統計
- **F9P出力**: NMEA 5%, UBX 95%
- **スマホ受信**: NMEA 100% (フィルタリング済み)
- **転送効率**: 約30-40%のデータのみを転送（不要なUBXを除外）

## 受信したNMEAデータ例

```
$GNRMC,024452.00,A,3519.82950,N,13931.09983,E,0.015,,281025,,,A,V*13
$GNGGA,024452.00,3519.82950,N,13931.09983,E,2,12,0.54,20.1,M,39.2,M,,0137*7F
$GNGSA,A,3,10,12,23,24,25,32,,,,,,,1.02,0.54,0.86,1*0E
$GNVTG,,T,,M,0.015,N,0.029,K,D*34
```

**位置情報**:
- 緯度: 35°19.82950'N (35.330491°N)
- 経度: 139°31.09983'E (139.518330°E)
- Fix状態: A (Active/有効)
- 衛星数: 12個
- HDOP: 0.54

## 最適化の推奨事項

### u-centerでの設定変更
現在F9PはUBX（95%）とNMEA（5%）を混在出力しています。スマホアプリがNMEAのみ必要な場合：

1. F9PをPCに接続してu-centerを起動
2. **UBX → CFG → PRT (Ports)** を選択
3. **Target: UART1** を選択
4. **Protocol Out**: UBXのチェックを外し、NMEAのみにチェック
5. **Send** ボタンをクリック
6. **UBX → CFG → CFG** で設定を保存

**効果**:
- 不要なデータ転送を削減
- 処理負荷を軽減
- バッテリー消費を改善

## ファイル構成

```
pocket-f9p/
├── src/
│   └── pocket_f9p/
│       └── main.py          # メインファームウェア
├── README.md
├── pyproject.toml
└── claude.md               # このファイル
```

## 技術仕様

### MicroPython環境
- **ボード**: XIAO ESP32C3
- **MicroPython**: v1.26.1 (ESP32_GENERIC_C3)
- **UART**: UART1, 115200 bps, 8N1
- **バッファ**: RX 2048バイト

### BLE設定
- **デバイス名**: "Pocket F9P"
- **MTU**: デフォルト（通常23バイト）
- **通知バッファ**: 512バイト

### パフォーマンス
- **ポーリング間隔**: 20ms
- **ステータス表示**: 5秒ごと
- **レイテンシ**: 約20-40ms（測定値）

## トラブルシューティング

### データが受信できない場合

1. **配線を確認**
   ```
   F9P TX → XIAO D1 (GPIO2)
   F9P RX → XIAO D2 (GPIO3)
   GND共通接続
   ```

2. **ボーレート検出ログを確認**
   - 起動時のログで検出されたボーレートを確認
   - `Detected GNSS data at baudrate: XXXXX`

3. **F9Pの電源とUART設定を確認**
   - F9Pが起動しているか
   - u-centerでUART1が有効か

### NMEAデータが少ない場合

- Extended monitoringのSummaryを確認
- NMEA出力率が低い場合、u-centerで出力メッセージを増やす

### BLE接続できない場合

- デバイスが"Pocket F9P"として表示されるか確認
- 他のBLEデバイスとのペアリングを解除
- XIAOを再起動

## 参考情報

### u-blox F9P
- [u-blox F9P データシート](https://www.u-blox.com/en/product/zed-f9p-module)
- [Interface Description](https://www.u-blox.com/sites/default/files/products/documents/u-blox-F9-HPG-1.32_InterfaceDescription_UBX-22008968.pdf)

### NMEA 0183
- [NMEA Sentences](https://www.gpsinformation.org/dale/nmea.htm)

### Nordic UART Service (NUS)
- [NUS Specification](https://developer.nordicsemi.com/nRF_Connect_SDK/doc/latest/nrf/libraries/bluetooth_services/services/nus.html)

## ライセンス

(プロジェクトのライセンスをここに記載)

## 変更履歴

### 2025-10-28
- ボーレート自動検出機能を実装
- NMEAフィルタリング機能を実装
- NMEA検証ロジックを強化
- 配線問題を修正
- 初回動作確認成功

## 貢献者

- 開発: Hayato
- 技術サポート: Claude (Anthropic)
