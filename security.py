import os
import socket
from ipaddress import ip_address, ip_network
from urllib.parse import urlparse


PRIVATE_NETWORKS = (
    ip_network("10.0.0.0/8"),
    ip_network("127.0.0.0/8"),
    ip_network("169.254.0.0/16"),
    ip_network("172.16.0.0/12"),
    ip_network("192.168.0.0/16"),
    ip_network("::1/128"),
    ip_network("fc00::/7"),
    ip_network("fe80::/10"),
)
LOCAL_HOSTNAMES = {"localhost", "localhost.localdomain"}


def env_enabled(name, default=False):
    fallback = "1" if default else "0"
    return os.environ.get(name, fallback).lower() in ("1", "true", "yes")


def is_private_host(hostname):
    if not hostname:
        return True
    normalized = hostname.strip().lower().rstrip(".")
    if normalized in LOCAL_HOSTNAMES:
        return True

    addresses = []
    try:
        addresses.append(ip_address(normalized))
    except ValueError:
        try:
            for family, _, _, _, sockaddr in socket.getaddrinfo(normalized, None):
                if family in (socket.AF_INET, socket.AF_INET6):
                    addresses.append(ip_address(sockaddr[0]))
        except socket.gaierror:
            return True

    return any(any(address in network for network in PRIVATE_NETWORKS) for address in addresses)


def is_monitor_url_allowed(url):
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        return False
    if env_enabled("ALLOW_PRIVATE_URLS"):
        return True
    return not is_private_host(parsed.hostname)
