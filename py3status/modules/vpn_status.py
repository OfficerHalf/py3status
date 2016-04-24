#!/usr/bin/env python3
"""
Drop-in replacement for i3status run_watch VPN module.

Expands on the i3status module by displaying the name of the connected vpn
using the NetworkManager python module.

Configuration parameters:
    check_pid: If true, act just like the default i3status module.
        (default False)
    pidfile: Same as i3status.conf pidfile, checked when check_pid is True.
        (default '/sys/class/net/vpn0/dev_id')
    cache_timeout: How often we refresh this module in seconds.
        (default 10)
    format: Format of the output.
        (default 'VPN: {name}')

Format string parameters:
    {name} The name and/or status of the VPN.

Requires:
    python-NetworkManager

@author Nathan Smith <nathan AT praisetopia.org>
"""

import NetworkManager
import dbus
from os import path
from dbus.mainloop.glib import DBusGMainLoop
DBusGMainLoop(set_as_default=True)
from gi.repository import GLib
from time import time


class Py3status:
    # Available Configuration Parameters
    pidfile = '/sys/class/net/vpn0/dev_id'
    check_pid = False
    cache_timeout = 0
    format = "VPN: {name}"

    def __init__(self):
        # Start event handler
        self.loop = GLib.MainLoop()
        self.bus = dbus.SystemBus(self.loop)
        self.bus.add_signal_receiver(self._vpn_signal_handler, dbus_interface="org.freedesktop.NetworkManager.VPN.Connection",
                                signal_name="PropertiesChanged")

    def _vpn_signal_handler(self, *args, **keywords):
        print("here!")
        #self.py3.update()

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
            'color': color
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
    print("Starting Loop.")
    x.loop.run()