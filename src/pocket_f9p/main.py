import struct
import time

import ubluetooth
from machine import UART, Pin

XIAO_TX_PIN = 2  # XIAO D1 (GPIO2)
XIAO_RX_PIN = 3  # XIAO D2 (GPIO3)

# Common baudrates for u-blox F9P (in priority order)
BAUDRATES = [9600, 38400, 115200, 57600, 19200, 230400]

# UART settings for u-blox F9P
# XIAO D1 (GPIO2 / TX) -> F9P RX
# XIAO D2 (GPIO3 / RX) -> F9P TX
uart = None


# Helper function to validate NMEA sentence
def is_valid_nmea_start(data, start_pos):
    """Check if position in data is a valid NMEA sentence start"""
    # Need at least "$GPXXX," (7 chars minimum)
    if start_pos + 6 >= len(data):
        return False

    # Must start with $
    if data[start_pos] != 0x24:  # '$'
        return False

    # Next 5 characters should be printable ASCII (talker ID + sentence type)
    for i in range(1, 6):
        c = data[start_pos + i]
        # Allow uppercase letters and digits
        if not ((65 <= c <= 90) or (48 <= c <= 57)):
            return False

    # 6th char should be comma
    if data[start_pos + 6] != 0x2C:  # ','
        return False

    return True


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

            if bytes_available > 0:
                print(f"  Iteration {i + 1}: {bytes_available} bytes in buffer")

        print(f"  Max bytes seen: {total_bytes}")

        # Read and check if it looks like NMEA or UBX data
        if total_bytes > 10:  # Need substantial data to verify
            test_data = uart.read(min(total_bytes, 200))
            print(f"  Sample data (hex): {test_data.hex()}")  # Print as hex
            print(f"  Sample data (raw): {test_data[:50]}")  # Print first 50 bytes

            # Check for printable ASCII (NMEA should be mostly printable)
            if test_data:
                printable_count = sum(
                    1 for b in test_data if 32 <= b <= 126 or b in [10, 13]
                )
                printable_pct = (
                    (100 * printable_count // len(test_data))
                    if len(test_data) > 0
                    else 0
                )
                print(
                    f"  Printable chars: {printable_count}/{len(test_data)} ({printable_pct}%)"
                )

            # Check for NMEA sentences (start with $) or UBX binary (starts with 0xB5 0x62)
            has_nmea = test_data and b"$" in test_data
            has_ubx = test_data and b"\xb5\x62" in test_data

            if has_nmea or has_ubx:
                protocol = "NMEA" if has_nmea else ""
                if has_ubx:
                    protocol += "+UBX" if protocol else "UBX"
                print(f"  -> Found {protocol} data!")

                # For NMEA, verify it's mostly printable (80%+)
                # For UBX binary, printable check doesn't apply
                if has_nmea and not has_ubx:
                    if printable_pct < 80:
                        print(
                            "  -> Rejected: NMEA data but not enough printable chars (wrong baudrate)"
                        )
                        uart.deinit()
                        continue

                print(f"Detected GNSS data at baudrate: {baudrate}")
                # Clear the buffer by reading remaining data
                if uart.any() > 0:
                    uart.read()
                return baudrate
            else:
                print("  -> Rejected: No valid NMEA ($) or UBX (0xB562) markers found")

        uart.deinit()

    # Fallback to 38400 (since user configured it in u-center)
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

# Additional diagnostic: Monitor UART for 5 seconds
print("\n=== Extended UART monitoring (5 seconds) ===")
print("Watching for data patterns and testing NMEA filter...")
uart_samples = []
nmea_samples = []
for i in range(10):  # 10 samples over 5 seconds
    time.sleep_ms(500)
    if uart.any() > 0:
        sample = uart.read(min(uart.any(), 500))
        uart_samples.append(sample)

        # Apply NMEA filter to this sample
        nmea_filtered = bytearray()
        j = 0
        while j < len(sample):
            if j < len(sample) - 1 and sample[j] == 0xB5 and sample[j + 1] == 0x62:
                # Skip UBX message
                if j + 6 <= len(sample):
                    payload_len = sample[j + 4] | (sample[j + 5] << 8)
                    ubx_msg_len = 6 + payload_len + 2
                    j += ubx_msg_len
                    continue
                else:
                    break
            elif sample[j] == 0x24:  # '$' - potential NMEA start
                # Validate it's a real NMEA sentence
                if is_valid_nmea_start(sample, j):
                    end = j
                    while end < len(sample) and sample[end] != 0x0A:
                        end += 1
                    if end < len(sample):
                        end += 1
                        nmea_filtered.extend(sample[j:end])
                    j = end
                else:
                    # False positive $, skip it
                    j += 1
            else:
                j += 1

        if len(nmea_filtered) > 0:
            nmea_samples.append(bytes(nmea_filtered))
            print(
                f"Sample {i + 1}: {len(sample)} bytes total, {len(nmea_filtered)} bytes NMEA"
            )
            print(f"  NMEA: {nmea_filtered[:80]}")  # Show first 80 bytes
        else:
            print(f"Sample {i + 1}: {len(sample)} bytes total, 0 bytes NMEA (UBX only)")
    else:
        print(f"Sample {i + 1}: 0 bytes")

if uart_samples:
    total_bytes = sum(len(s) for s in uart_samples)
    total_nmea = sum(len(s) for s in nmea_samples)
    print("\nSummary:")
    print(f"  Total samples: {len(uart_samples)}")
    print(f"  Total bytes received: {total_bytes}")
    print(
        f"  NMEA bytes (after filtering): {total_nmea} ({100 * total_nmea // total_bytes if total_bytes > 0 else 0}%)"
    )
    print(
        f"  UBX bytes (filtered out): {total_bytes - total_nmea} ({100 * (total_bytes - total_nmea) // total_bytes if total_bytes > 0 else 0}%)"
    )
else:
    print("\n!!! WARNING: No data received at all !!!")
    print("Possible issues:")
    print("  1. F9P is not powered on")
    print("  2. Wiring is incorrect (check TX/RX and GND)")
    print("  3. F9P UART1 is disabled or not outputting data")

print("===========================================\n")

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
            # Read data from F9P
            f9p_data = uart.read(bytes_available)
            if f9p_data and len(f9p_data) > 0:
                # Filter: Only forward NMEA data (starts with $), skip UBX binary (starts with 0xB5)
                # Split and filter NMEA sentences
                nmea_only = bytearray()
                i = 0
                while i < len(f9p_data):
                    # Skip UBX messages (0xB5 0x62 + 4 byte header + payload + 2 byte checksum)
                    if (
                        i < len(f9p_data) - 1
                        and f9p_data[i] == 0xB5
                        and f9p_data[i + 1] == 0x62
                    ):
                        # UBX message detected, skip it
                        if i + 6 <= len(f9p_data):
                            # Read payload length (little-endian uint16 at offset 4-5)
                            payload_len = f9p_data[i + 4] | (f9p_data[i + 5] << 8)
                            ubx_msg_len = (
                                6 + payload_len + 2
                            )  # header + payload + checksum
                            i += ubx_msg_len
                            continue
                        else:
                            # Incomplete UBX message, skip to end
                            break
                    # Keep NMEA data only
                    elif f9p_data[i] == 0x24:  # '$' - potential NMEA start
                        # Validate it's a real NMEA sentence
                        if is_valid_nmea_start(f9p_data, i):
                            # Find end of NMEA sentence (CR LF)
                            end = i
                            while end < len(f9p_data) and f9p_data[end] != 0x0A:
                                end += 1
                            if end < len(f9p_data):
                                end += 1  # Include the LF
                                nmea_only.extend(f9p_data[i:end])
                            i = end
                        else:
                            # False positive $, skip it
                            i += 1
                    else:
                        # Other data, skip
                        i += 1

                if len(nmea_only) > 0:
                    print(
                        f"Read {len(f9p_data)} bytes from F9P, forwarding {len(nmea_only)} bytes NMEA to BLE"
                    )

                    try:
                        # Send via BLE Notify
                        ble.gatts_notify(
                            conn_handle_global, tx_handle, bytes(nmea_only)
                        )
                        print(f"Sent {len(nmea_only)} bytes to BLE")
                    except OSError as e:
                        # Connection lost
                        print(f"Error: BLE connection lost during notify: {e}")
                else:
                    print(
                        f"Read {len(f9p_data)} bytes from F9P (UBX only, not forwarding)"
                    )

    time.sleep_ms(20)
