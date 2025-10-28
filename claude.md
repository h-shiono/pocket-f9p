# Pocket F9P - GNSS RTK over BLE

## プロジェクト概要

XIAO ESP32C3上のMicroPythonで動作する、u-blox F9P GNSS受信機とスマートフォンをBLE接続するファームウェアです。

### 機能
- F9PからのNMEAデータをBLE経由でスマートフォンに送信（シンプルな転送のみ）
- スマートフォンからのRTCM補正データをF9Pに転送
- 自動ボーレート検出（38400/9600/115200/57600/19200/230400 bps、38400を優先）

## ハードウェア構成

### 接続
```
F9P UART2          XIAO ESP32C3
---------------------------------
TX2        →       D2 (GPIO3, RX)
RX2        ←       D1 (GPIO2, TX)
GND        -       GND
```

### F9P設定
- **UART2ボーレート**: 38400 bps（推奨）
- **Protocol Out**: NMEA のみ（UBXは無効化）

## 設計方針

### シンプルな構成
以前のバージョンでは複数のデータ転送モード（NMEA/RAW/UBX）とフィルタリング機能を実装していましたが、以下の理由でシンプルな構成に戻しました：

1. **UBXデータ転送の問題**: フルコンステレーション時、UBXバイナリデータ量が多すぎて1秒周期の転送に間に合わない
2. **用途の明確化**: 本ファームウェアの主目的はスマートフォンアプリでのナビゲーション用途
3. **保守性の向上**: 複雑なフィルタリングロジックを削除し、シンプルで安定した実装に

### 現在の実装
- **F9P側**: NMEA出力のみに設定（u-centerで設定）
- **XIAO側**: 受信したNMEAデータをそのままBLE経由で転送（フィルタリングなし）
- **データ量**: 約100-200バイト/秒（NMEA標準メッセージのみ）

## 実装した機能

### 1. ボーレート自動検出 (`detect_baudrate()`)
```python
def detect_baudrate():
    """Detect F9P baudrate by trying common rates"""
    # 38400を優先的に試行
    for baudrate in [38400, 9600, 115200, 57600, 19200, 230400]:
        # 2秒間データを監視
        # NMEA ($) マーカーを検出
        # 印字可能文字の割合をチェック（80%以上）
```

**特徴**:
- 38400bpsを最初に試行（推奨設定）
- NMEAデータの特徴（印字可能文字率80%以上）で検証
- 検出失敗時は38400bpsにフォールバック

### 2. BLE Nordic UART Service (NUS)
- Service UUID: `6E400001-B5A3-F393-E0A9-E50E24DCCA9E`
- TX Characteristic: `6E400003-...` (Notify) - F9P → スマートフォン
- RX Characteristic: `6E400002-...` (Write) - スマートフォン → F9P（RTCM補正データ）

### 3. シンプルなデータ転送
```python
# メインループ
if conn_handle_global is not None:
    bytes_available = uart.any()
    if bytes_available > 0:
        nmea_data = uart.read(bytes_available)
        ble.gatts_notify(conn_handle_global, tx_handle, nmea_data)
```

**特徴**:
- フィルタリングなし、受信データをそのまま転送
- 低レイテンシ（20-40ms）
- シンプルで安定した実装

## 動作確認ログ

### 起動時
```
Detecting F9P baudrate...
Trying baudrate: 38400...
  -> Detected NMEA data at 38400 bps
Using baudrate: 38400
Main loop starting. Waiting for BLE connection...
Advertising as 'Pocket F9P'...
```

### BLE接続後
```
BLE Connected
Status: BLE=Connected, UART buffer=0 bytes
Forwarded 85 bytes NMEA to BLE
Forwarded 78 bytes NMEA to BLE
```

### RTCM補正データ受信時
```
Received 124 bytes from BLE, writing to F9P UART
```

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

## F9P設定方法（u-centerを使用）

### UART2設定
1. F9PをPCに接続してu-centerを起動
2. **UBX → CFG → PRT (Ports)** を選択
3. **Target: UART2** を選択
4. **Baudrate**: 38400
5. **Protocol In**: UBX + NMEA + RTCM3（補正データ受信用）
6. **Protocol Out**: NMEA のみ（UBXのチェックを外す）
7. **Send** ボタンをクリック
8. **UBX → CFG → CFG** で設定を保存

### NMEAメッセージ出力設定（オプション）
必要に応じて出力するNMEAメッセージを調整：

1. **UBX → CFG → MSG** を選択
2. 各メッセージ（GGA, RMC, GSA, VTGなど）の出力レートを設定
3. UART2の出力レート（1秒に1回など）を設定

**推奨メッセージ**:
- GNRMC: 位置、速度、時刻
- GNGGA: 位置、Fix品質、衛星数
- GNGSA: 衛星情報、DOP
- GNVTG: 速度情報

## ファイル構成

```
pocket-f9p/
├── src/
│   └── pocket_f9p/
│       └── main.py          # メインファームウェア（約206行、シンプル実装）
├── README.md                 # ユーザー向けドキュメント
├── CLAUDE.md                 # このファイル（開発者向けドキュメント）
├── pyproject.toml
└── case/                     # 3Dプリント用ケースモデル
```

## 技術仕様

### MicroPython環境
- **ボード**: XIAO ESP32C3
- **MicroPython**: v1.26.1 (ESP32_GENERIC_C3)
- **UART**: UART1, 38400 bps, 8N1
- **バッファ**: RX 2048バイト

### BLE設定
- **デバイス名**: "Pocket F9P"
- **MTU**: デフォルト（通常23バイト）
- **通知バッファ**: 512バイト

### パフォーマンス
- **ポーリング間隔**: 20ms
- **ステータス表示**: 5秒ごと
- **レイテンシ**: 約20-40ms

## トラブルシューティング

### データが受信できない場合

1. **配線を確認**
   ```
   F9P TX2 → XIAO D2 (GPIO3)
   F9P RX2 → XIAO D1 (GPIO2)
   GND共通接続
   ```

2. **ボーレート検出ログを確認**
   - 起動時のログで検出されたボーレートを確認
   - `Detected NMEA data at XXXXX bps`

3. **F9PのUART設定を確認**
   - u-centerでUART2が有効か
   - Protocol OutがNMEA のみになっているか
   - ボーレートが38400bpsか

### NMEAデータが表示されない場合

1. **u-centerでNMEA出力を確認**
   - UBX → MSG で各NMEAメッセージの出力レートを確認
   - UART2で出力されているか確認

2. **XIAOのログを確認**
   - "Forwarded XX bytes NMEA to BLE" が表示されているか
   - データ量が0の場合、F9P側の設定を確認

### BLE接続できない場合

1. **デバイス表示を確認**
   - スマートフォンで"Pocket F9P"が表示されるか

2. **他のBLE接続を解除**
   - 他のBLEデバイスとのペアリングを解除

3. **XIAOを再起動**
   - 電源を入れ直す

## 参考情報

### u-blox F9P
- [u-blox F9P データシート](https://www.u-blox.com/en/product/zed-f9p-module)
- [Interface Description](https://www.u-blox.com/sites/default/files/products/documents/u-blox-F9-HPG-1.32_InterfaceDescription_UBX-22008968.pdf)

### NMEA 0183
- [NMEA Sentences](https://www.gpsinformation.org/dale/nmea.htm)

### Nordic UART Service (NUS)
- [NUS Specification](https://developer.nordicsemi.com/nRF_Connect_SDK/doc/latest/nrf/libraries/bluetooth_services/services/nus.html)

## 変更履歴

### 2025-10-28 (v2 - Simple)
- **設計方針の変更**: 複雑なフィルタリング機能を削除し、シンプルな転送のみに
- **F9P設定の明確化**: NMEA出力のみ、38400bps
- **コードのリファクタリング**: 479行 → 206行（約60%削減）
- **削除した機能**:
  - 3つのデータ転送モード（NMEA/RAW/UBX）
  - BLE経由でのモード切り替えコマンド
  - UBX/NMEAフィルタリングロジック
  - 拡張UART監視機能
- **改善点**:
  - ボーレート検出を38400優先に変更
  - シンプルで安定した実装
  - 保守性の向上

### 2025-10-28 (v1 - Complex)
- ボーレート自動検出機能を実装
- 3つのデータ転送モード（NMEA/RAW/UBX）を実装
- BLE経由でのモード切り替えコマンドを実装
- NMEA検証ロジックを強化（誤検出対策）
- 配線問題を修正
- 初回動作確認成功（NMEAモード）
- RAWモードで研究・デバッグ用途に対応

## 貢献者

- 開発: Hayato
- 技術サポート: Claude (Anthropic)
