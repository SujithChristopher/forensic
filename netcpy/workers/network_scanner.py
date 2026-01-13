"""NetworkScanner - Background thread for scanning network for Raspberry Pi devices with SSH"""

import socket
import threading
import ipaddress
from PySide6.QtCore import QThread, Signal


class NetworkScanner(QThread):
    """Scans local network for Raspberry Pi devices with SSH enabled"""

    device_found = Signal(str, str)  # (ip_address, display_name)
    scan_progress = Signal(int)  # percentage
    scan_complete = Signal()

    def __init__(self, network_range: str):
        """Initialize NetworkScanner

        Args:
            network_range: Network range to scan (e.g., "192.168.1.0/24")
        """
        super().__init__()
        self.network_range = network_range
        self.stop_flag = False

    def run(self):
        """Run the network scan"""
        try:
            # Parse the network range
            network = ipaddress.IPv4Network(self.network_range)
            total_hosts = network.num_addresses - 2  # Subtract network and broadcast addresses
            scanned_hosts = 0

            # Function to check a single host
            def check_host(ip):
                nonlocal scanned_hosts

                if self.stop_flag:
                    return

                # Try to resolve hostname
                hostname = ""
                try:
                    hostname = socket.getfqdn(str(ip))
                    if hostname == str(ip):  # If resolution failed
                        hostname = ""
                except Exception:
                    pass

                # Check if port 22 is open (SSH)
                try:
                    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                    sock.settimeout(0.5)
                    result = sock.connect_ex((str(ip), 22))
                    sock.close()

                    if result == 0:  # Port is open
                        # Check if it might be a Raspberry Pi
                        is_pi = False
                        if "raspberry" in hostname.lower() or not hostname:
                            is_pi = True

                        if is_pi:
                            display_name = f"{hostname} ({ip})" if hostname else str(ip)
                            self.device_found.emit(str(ip), display_name)
                except Exception:
                    pass

                # Update progress
                scanned_hosts += 1
                self.scan_progress.emit(int((scanned_hosts / total_hosts) * 100))

            # Skip the network and broadcast addresses
            hosts = [ip for ip in network.hosts()]

            # Use threads for faster scanning
            threads = []
            max_threads = 50

            for i in range(0, len(hosts), max_threads):
                if self.stop_flag:
                    break

                batch = hosts[i : i + max_threads]
                threads = []

                for ip in batch:
                    if self.stop_flag:
                        break
                    t = threading.Thread(target=check_host, args=(ip,))
                    threads.append(t)
                    t.start()

                # Wait for all threads to complete
                for t in threads:
                    t.join()

            self.scan_complete.emit()

        except Exception as e:
            print(f"Scan error: {str(e)}")
            self.scan_complete.emit()

    def stop(self):
        """Stop the scan"""
        self.stop_flag = True
