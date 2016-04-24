"""
Drop-in replacement for i3status run_watch VPN module.

Expands on the i3status module by displaying the name of the connected vpn
using the NetworkManager python module.

Configuration parameters:
    check_pid: If true, act just like the default i3status module.
        (default False)
    pidfile: Path to pidfile, checked when check_pid is True.
        (default '/sys/class/net/vpn0/dev_id')
    cache_timeout: How often we refresh this module in seconds.
        (default 10)
    format: Format of the output.
        (default 'VPN: {name}')

Format string parameters:
    {name} The name and/or status of the VPN.

Requires:
    python-NetworkManager
"""

import NetworkManager
from os import path
from time import time


class Py3status:
    # Available Configuration Parameters
    pidfile = '/sys/class/net/vpn0/dev_id'
    check_pid = False
    cache_timeout = 10
    format = "VPN: {name}"

    def _get_vpn_status(self):
        """Returns None if no VPN active, Id if active."""
        vpn = None
        # Search for the first VPN in NetworkManager.ActiveConnections
        for conn in NetworkManager.NetworkManager.ActiveConnections:
            if conn.Vpn:
                vpn = conn.Id
                break
        return vpn

    def _check_pid(self):
        """Returns True if pidfile exists, False otherwise."""
        return path.isfile(self.pidfile)

    # Method run by py3status
    def return_status(self, i3s_outputs, i3s_config):
        """Returns response dict"""
        # Set 'no', color_bad as default output. Replaced if VPN active.
        name = "no"
        color = i3s_config["color_bad"]

        # If we are acting like the default i3status module
        if self.check_pid:
            if self._check_pid():
                name = "yes"
                color = i3s_config["color_good"]

        # Otherwise, find the VPN name, if it is active
        else:
            vpn = self._get_vpn_status()
            if vpn:
                name = vpn
                color = i3s_config["color_good"]

        # Format and create the response dict
        full_text = self.format.format(name=name)
        response = {
            'full_text': full_text,
            'color': color,
            'cached_until': time() + self.cache_timeout
        }
        return response

if __name__ == "__main__":
    from time import sleep
    x = Py3status()
    config = {
        'color_bad': '#FF0000',
        'color_degraded': '#FFFF00',
        'color_good': '#00FF00'
    }
    while True:
        print(x.return_status([], config))
        sleep(1)
