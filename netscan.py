import argparse
import socket
import subprocess
import platform
import re
try:
    from scapy.all import ARP, Ether, srp
    SCAPY_AVAILABLE = True
except ImportError:
    SCAPY_AVAILABLE = False

def scan_scapy(ip_range):
    """
    Scans the network using ARP requests to find active devices (Requires Scapy).
    """
    print(f"[*] Scanning {ip_range} using Scapy...")
    # Create an ARP request packet
    arp_request = ARP(pdst=ip_range)
    # Create an Ethernet frame to broadcast the ARP request
    broadcast = Ether(dst="ff:ff:ff:ff:ff:ff")
    # Combine the Ethernet frame and ARP request
    arp_request_broadcast = broadcast/arp_request
    
    # Send the packet and receive the response
    answered_list = srp(arp_request_broadcast, timeout=1, verbose=False)[0]
    
    clients_list = []
    for element in answered_list:
        client_dict = {"ip": element[1].psrc, "mac": element[1].hwsrc}
        clients_list.append(client_dict)
        
    return clients_list

def get_local_ip():
    """Gets the local IP address of the machine."""
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        # Doesn't even have to be reachable
        s.connect(('10.255.255.255', 1))
        IP = s.getsockname()[0]
    except Exception:
        IP = '127.0.0.1'
    finally:
        s.close()
    return IP

def scan_arp_table():
    """
    Scans the network by reading the local ARP table.
    Works without external libraries.
    """
    print("[*] Retrieving devices from local ARP cache...")
    clients_list = []
    
    if platform.system() == "Windows":
        output = subprocess.check_output("arp -a", shell=True).decode()
        # Regex to match IP and MAC addresses in Windows 'arp -a' output
        pattern = re.compile(r"(\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3})\s+([0-9a-fA-F-]{17})\s+(\w+)")
        for line in output.split('\n'):
            match = pattern.search(line)
            if match:
                ip, mac, type_ = match.groups()
                mac = mac.replace('-', ':')
                clients_list.append({"ip": ip, "mac": mac})
    else:
        # Linux / macOS
        output = subprocess.check_output("arp -a", shell=True).decode()
        pattern = re.compile(r"\((.*?)\) at (.*?)\s")
        for line in output.split('\n'):
            match = pattern.search(line)
            if match:
                ip, mac = match.groups()
                clients_list.append({"ip": ip, "mac": mac})

    return clients_list

def print_result(results_list):
    """
    Prints the scanned results in a formatted table.
    """
    print("\nIP Address\t\tMAC Address")
    print("-" * 45)
    for client in results_list:
        print(f"{client['ip']:<20}\t{client['mac']}")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Network Device Scanner")
    parser.add_argument("-t", "--target", help="Target IP range (e.g., 192.168.1.1/24) for Scapy scan.", required=False)
    args = parser.parse_args()
    
    scan_result = []
    
    local_ip = get_local_ip()
    print(f"[+] Your local IP is: {local_ip}")

    # Use Scapy if target is provided and Scapy is installed
    if args.target:
        if SCAPY_AVAILABLE:
            scan_result = scan_scapy(args.target)
        else:
            print("[!] Target provided, but 'scapy' is not installed.")
            print("    Install it using: pip install scapy")
            print("    Falling back to ARP table scan...\n")
            scan_result = scan_arp_table()
    else:
        # Fallback to scanning the current ARP table (no active scanning, just parsing cache)
        if SCAPY_AVAILABLE:
            print("[i] Hint: You can do an active network sweep by providing a target range (e.g., -t 192.168.1.0/24)")
        scan_result = scan_arp_table()
        
    print_result(scan_result)
