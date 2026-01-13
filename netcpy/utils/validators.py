"""Validators - Utility functions for validating inputs"""

import ipaddress
import os
import re


def validate_hostname(hostname: str) -> tuple[bool, str]:
    """Validate hostname or IP address

    Args:
        hostname: Hostname or IP address to validate

    Returns:
        Tuple of (is_valid, error_message)
    """
    if not hostname or not hostname.strip():
        return False, "Hostname cannot be empty"

    hostname = hostname.strip()

    # Try to parse as IP address
    try:
        ipaddress.ip_address(hostname)
        return True, ""
    except ValueError:
        pass

    # Try to validate as hostname
    # Hostname regex pattern
    hostname_pattern = r"^(?:[a-zA-Z0-9](?:[a-zA-Z0-9\-]{0,61}[a-zA-Z0-9])?\.)*[a-zA-Z0-9](?:[a-zA-Z0-9\-]{0,61}[a-zA-Z0-9])?\.?$"

    if re.match(hostname_pattern, hostname):
        # Valid hostname format
        if len(hostname) <= 253:
            return True, ""

    return False, f"Invalid hostname: {hostname}"


def validate_directory(directory: str, must_exist: bool = False) -> tuple[bool, str]:
    """Validate directory path

    Args:
        directory: Directory path to validate
        must_exist: Whether directory must exist

    Returns:
        Tuple of (is_valid, error_message)
    """
    if not directory or not directory.strip():
        return False, "Directory path cannot be empty"

    directory = directory.strip()

    # Check if path is absolute
    if not os.path.isabs(directory):
        return False, "Directory path must be absolute"

    if must_exist:
        if not os.path.exists(directory):
            return False, f"Directory does not exist: {directory}"
        if not os.path.isdir(directory):
            return False, f"Path is not a directory: {directory}"

    return True, ""


def validate_network_range(network_range: str) -> tuple[bool, str]:
    """Validate network range in CIDR notation

    Args:
        network_range: Network range (e.g., "192.168.1.0/24")

    Returns:
        Tuple of (is_valid, error_message)
    """
    if not network_range or not network_range.strip():
        return False, "Network range cannot be empty"

    network_range = network_range.strip()

    try:
        network = ipaddress.IPv4Network(network_range)
        return True, ""
    except ValueError as e:
        return False, f"Invalid network range: {str(e)}"


def validate_connection_settings(hostname: str, username: str, password: str) -> tuple[bool, str]:
    """Validate all connection settings together

    Args:
        hostname: Remote hostname or IP
        username: SSH username
        password: SSH password

    Returns:
        Tuple of (is_valid, error_message)
    """
    # Validate hostname
    valid, msg = validate_hostname(hostname)
    if not valid:
        return False, msg

    # Validate username
    if not username or not username.strip():
        return False, "Username cannot be empty"

    if len(username) > 32:
        return False, "Username too long (max 32 characters)"

    # Validate password
    if not password:
        return False, "Password cannot be empty"

    if len(password) > 256:
        return False, "Password too long (max 256 characters)"

    return True, ""


def validate_profile_name(name: str) -> tuple[bool, str]:
    """Validate profile name

    Args:
        name: Profile name

    Returns:
        Tuple of (is_valid, error_message)
    """
    if not name or not name.strip():
        return False, "Profile name cannot be empty"

    name = name.strip()

    if len(name) > 64:
        return False, "Profile name too long (max 64 characters)"

    # Allow alphanumeric, spaces, hyphens, and underscores
    if not re.match(r"^[a-zA-Z0-9\s\-_]+$", name):
        return False, "Profile name can only contain letters, numbers, spaces, hyphens, and underscores"

    return True, ""
