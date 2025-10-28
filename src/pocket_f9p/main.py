import struct
import time

import ubluetooth
from machine import UART, Pin

XIAO_TX_PIN = 3  # XIAO D1
XIAO_RX_PIN = 2  # XIAO D2

# UART settings for u-blox F9P
# XIAO D1 (GPIO2) -> F9P RX
# XIAO D2 (GPIO3) -> F9P TX
uart = UART(1, baudrate=38400, tx=Pin(XIAO_TX_PIN), rx=Pin(XIAO_RX_PIN), rxbuf=1024)

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

        # try:
        #    ble.gap_negotiate_mtu(conn_handle)
        #    print("MTU negotiation requested...")
        # except Exception as e:
        #    print(f"MTU negotiation failed: {e}")

    elif event == _IRQ_CENTRAL_DISCONNECT:
        # Disconnected from smartphone
        conn_handle_global = None
        print("BLE Disconnected")
        # Restart advertising (waiting for connection)
        advertise()

    elif event == _IRQ_GATTS_WRITE:
        # Data written from smartphone (RTCM data received!)
        conn_handle, value_handle = data
        if conn_handle == conn_handle_global and value_handle == rx_handle:
            # Write to UART (F9P)
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
# F9P to Smartphone data forwarding
print("Main loop starting. Waiting for BLE connection...")
while True:
    if conn_handle_global is not None:
        # Data available from F9P
        if uart.any():
            # Read data from F9P
            f9p_data = uart.read()
            if not f9p_data:
                continue

            print(f"Read {len(f9p_data)} bytes from F9P UART, sending to BLE")

            try:
                # Send via BLE Notify
                ble.gatts_notify(conn_handle_global, tx_handle, f9p_data)
                print(f"Sent {len(f9p_data)} bytes to BLE")
            except OSError:
                # Connection lost
                print("Error: BLE connection lost during notify")

    time.sleep_ms(20)
