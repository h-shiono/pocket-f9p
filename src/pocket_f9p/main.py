import struct
import time

import ubluetooth
from machine import UART, Pin

XIAO_TX_PIN = 2  # XIAO D1 (GPIO2)
XIAO_RX_PIN = 3  # XIAO D2 (GPIO3)

# Common baudrates for u-blox F9P (in priority order)
# 38400 is tried first as it's the configured baudrate
BAUDRATES = [38400, 9600, 115200, 57600, 19200, 230400]

# UART settings for u-blox F9P
# XIAO D1 (GPIO2 / TX) -> F9P RX
# XIAO D2 (GPIO3 / RX) -> F9P TX
uart = None


def detect_baudrate():
    """Detect F9P baudrate by trying common rates"""
    global uart

    for baudrate in BAUDRATES:
        print(f"Trying baudrate: {baudrate}...")
        uart = UART(
            1,
            baudrate=baudrate,
            tx=Pin(XIAO_TX_PIN),
            rx=Pin(XIAO_RX_PIN),
            rxbuf=2048,
            timeout=100,
        )

        # Wait for data - check multiple times over 2 seconds
        # (NMEA messages typically sent at 1Hz)
        total_bytes = 0
        for i in range(4):  # Check 4 times over 2 seconds
            time.sleep_ms(500)
            bytes_available = uart.any()
            total_bytes = max(total_bytes, bytes_available)

        # Read and check if it looks like NMEA data
        if total_bytes > 10:  # Need substantial data to verify
            test_data = uart.read(min(total_bytes, 200))

            # Check for NMEA sentences (start with $)
            # NMEA should be mostly printable ASCII
            if test_data and b"$" in test_data:
                printable_count = sum(
                    1 for b in test_data if 32 <= b <= 126 or b in [10, 13]
                )
                printable_pct = (
                    (100 * printable_count // len(test_data))
                    if len(test_data) > 0
                    else 0
                )

                # NMEA should be 80%+ printable characters
                if printable_pct >= 80:
                    print(f"  -> Detected NMEA data at {baudrate} bps")
                    # Clear the buffer by reading remaining data
                    if uart.any() > 0:
                        uart.read()
                    return baudrate

        uart.deinit()

    # Fallback to 38400 (configured baudrate)
    print("Could not detect baudrate, defaulting to 38400")
    uart = UART(
        1,
        baudrate=38400,
        tx=Pin(XIAO_TX_PIN),
        rx=Pin(XIAO_RX_PIN),
        rxbuf=2048,
        timeout=100,
    )
    return 38400


print("Detecting F9P baudrate...")
detected_baudrate = detect_baudrate()
print(f"Using baudrate: {detected_baudrate}")

# BLE settings (Nordic UART Service - NUS)
BLE_NAME = "Pocket F9P"
_IRQ_CENTRAL_CONNECT = 1
_IRQ_CENTRAL_DISCONNECT = 2
_IRQ_GATTS_WRITE = 3

# NUS Definitions
_UART_UUID = ubluetooth.UUID("6E400001-B5A3-F393-E0A9-E50E24DCCA9E")
_UART_TX_CHAR_UUID = ubluetooth.UUID("6E400003-B5A3-F393-E0A9-E50E24DCCA9E")
_UART_RX_CHAR_UUID = ubluetooth.UUID("6E400002-B5A3-F393-E0A9-E50E24DCCA9E")

# Define the UART service
uart_service = (
    _UART_UUID,
    (
        (_UART_TX_CHAR_UUID, ubluetooth.FLAG_NOTIFY),
        (_UART_RX_CHAR_UUID, ubluetooth.FLAG_WRITE | ubluetooth.FLAG_WRITE_NO_RESPONSE),
    ),
)

ble = ubluetooth.BLE()
ble.active(True)

# Register the service
((tx_handle, rx_handle),) = ble.gatts_register_services((uart_service,))

# Set buffer sizes
ble.gatts_set_buffer(rx_handle, 512, True)
ble.gatts_set_buffer(tx_handle, 512, True)

# connection handle
conn_handle_global = None


# BLE callback function
def ble_irq(event, data):
    global conn_handle_global

    if event == _IRQ_CENTRAL_CONNECT:
        # Connected to a smartphone
        conn_handle, _, _ = data
        conn_handle_global = conn_handle
        print("BLE Connected")

    elif event == _IRQ_CENTRAL_DISCONNECT:
        # Disconnected from smartphone
        conn_handle_global = None
        print("BLE Disconnected")
        # Restart advertising (waiting for connection)
        advertise()

    elif event == _IRQ_GATTS_WRITE:
        # Data written from smartphone (RTCM correction data)
        conn_handle, value_handle = data
        if conn_handle == conn_handle_global and value_handle == rx_handle:
            # Read data from BLE
            data_received = ble.gatts_read(rx_handle)
            print(f"Received {len(data_received)} bytes from BLE, writing to F9P UART")

            bytes_written = uart.write(data_received)
            if bytes_written is None or bytes_written < len(data_received):
                print("Warning: Not all data was written to UART")


# Register the BLE event handler
ble.irq(ble_irq)


# Advertising payload helper (minimal: flags + complete local name)
def advertising_payload(name=None):
    # Flags: LE General Discoverable Mode, BR/EDR not supported
    payload = bytearray(b"\x02\x01\x06")
    if name:
        name_bytes = name.encode()
        payload += struct.pack("BB", len(name_bytes) + 1, 0x09) + name_bytes
    return payload


# Start advertising
def advertise():
    payload = advertising_payload(name=BLE_NAME)
    ble.gap_advertise(100000, adv_data=payload)
    print(f"Advertising as '{BLE_NAME}'...")


advertise()

# Main loop
# F9P to Smartphone data forwarding (NMEA only)
print("Main loop starting. Waiting for BLE connection...")
print(
    f"UART initialized: baudrate={detected_baudrate}, tx=GPIO{XIAO_TX_PIN}, rx=GPIO{XIAO_RX_PIN}"
)

loop_count = 0
while True:
    # Debug: Print status every 5 seconds
    loop_count += 1
    if loop_count % 250 == 0:  # 250 * 20ms = 5 seconds
        bytes_available = uart.any()
        print(
            f"Status: BLE={'Connected' if conn_handle_global else 'Disconnected'}, UART buffer={bytes_available} bytes"
        )

    if conn_handle_global is not None:
        # Check if data available from F9P
        bytes_available = uart.any()
        if bytes_available > 0:
            # Read NMEA data from F9P
            nmea_data = uart.read(bytes_available)
            if nmea_data and len(nmea_data) > 0:
                try:
                    # Forward all NMEA data via BLE
                    ble.gatts_notify(conn_handle_global, tx_handle, nmea_data)
                    print(f"Forwarded {len(nmea_data)} bytes NMEA to BLE")
                except OSError as e:
                    # Connection lost
                    print(f"Error: BLE connection lost during notify: {e}")

    time.sleep_ms(20)
