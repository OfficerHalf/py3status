# -*- coding: utf-8 -*-
"""
Show the latest notification from Pushbullet.

Uses asyncio and websockets to show the latest notification from Pushbullet.
Clicking on the module will show the complete message using notify-send.

Configuration parameters:
    api_key: Your Pushbullet API token. This *MUST* be set for the module to
        work. Retrieve from https://www.pushbullet.com/#settings (default None)
    cache_timeout: How often the module should update. Pushbullet sends a
        keep-alive message every 30 seconds, so should be set to at least 30.
        (default 31)
    format: The output when there is a notification to display. See
        placeholders below. (default ": {msg}")
    format_none: What is displayed when there is no notification to display.
        (default "")
    max_len: How many characters to display when using the {msg} placeholder.
        Set to 0 to set no maximum. (default 20)
    timeout: If True, the currently displayed notification will expire after
        cache_timeout seconds. If false, the notification will stay until
        clicked on. (default True)

Format of string placeholders:
    {title} - The title field of a notification. Note: May be None if no title
        is given.
    {body} - The body field of a notification.
    {msg} - Both the title (if present) and the body field of a notification,
        joined into one string of the format "title: body". When used,
        max_len will be applied.

Requires:
    Python 3.4+ for asyncio
    A Pushbullet account: (https://www.pushbullet.com/)
    websockets: (https://github.com/aaugustin/websockets)
    requests: (https://github.com/kennethreitz/requests)

@author OfficerHalf
"""

from threading import Thread
import asyncio
import websockets
import requests
import subprocess
import json
import time

PB_PUSHES = "https://api.pushbullet.com/v2/pushes"
PB_STREAM = "wss://stream.pushbullet.com/websocket/"


class Py3status:
    """
    """
    # available configuration parameters
    api_key = None
    cache_timeout = 31
    format = ": {msg}"
    format_none = ""
    max_len = 20
    timeout = True

    def __init__(self):
        self.clicked = True
        self.connected = True
        self.last_nop = 0
        self.last_push = None
        self.thread_started = False

    def update(self, i3s_output_list, i3s_config):
        """Py3status calls this function."""
        if not self.thread_started:
            t = Thread(target=self._start_listen)
            t.daemon = True
            t.start()
            self.thread_started = True
        color = self._get_color()
        status = self._get_status()
        response = {
            'cached_until': self.cache_timeout,
            'color': i3s_config[color],
            'full_text': status
            }
        return response

    def on_click(self, i3s_output_list, i3s_config, event):
        """If there is a push, show it with notify-send."""
        if self.last_push:
            title = "Pushbullet"
            if self.last_push["title"]:
                title = self.last_push["title"]
            body = self.last_push["body"]
            subprocess.call([
                'notify-send', title, body,
                '-t', '4000'],
                stdout=open("/dev/null"),
                stderr=open("/dev/null"))
            self.clicked = True

    def _get_color(self):
        """Set the color for update.

        color_bad: not received a nop in 60 seconds or are not connected
        color_degraded: connected, but no nop in 30 seconds
        color_good: have seen a push/nop
        """
        if self.connected:
            color = "color_good"
            diff = time.time() - self.last_nop
            if diff > 60:
                pass
                color = "color_bad"
            elif diff > 30:
                pass
                color = "color_degraded"
        else:
            color = "color_bad"
        return color

    def _get_status(self):
        """Get the full text for the module."""
        status = self.format_none
        if self.last_push and not self.clicked:
            diff = time.time() - self.last_push["time"]
            if diff > self.cache_timeout:
                self.clicked = True
                return self.format_none
            title = self.last_push["title"]
            body = self.last_push["body"]
            if title:
                msg = title + ": " + body
            else:
                msg = body
            if self.max_len > 0 and len(msg) > self.max_len:
                msg = msg[:self.max_len]+"..."

            status = self.format.format(msg=msg, title=title, body=body)
        return status

    def _get_latest_push(self, push=None):
        if not push:
            payload = {"limit": "1", "active": "true"}
            r = requests.get(PB_PUSHES, auth=(self.api_key, ""), params=payload)
            push = r.json()["pushes"][0]
        if "type" in push.keys() and not push["type"] == "dismissal":
            title = None
            body = None
            if "title" in push.keys():
                title = push["title"]
            if "body" in push.keys():
                body = push["body"]
            self.last_push = {"body": body, "title": title, "time": time.time()}
            self.clicked = False
        # This is a notification dismissal, we should just clear the status
        else:
            self.clicked = True

    def _start_listen(self):
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        loop.run_until_complete(self._listen())

    @asyncio.coroutine
    def _listen(self):
        # Connect to PB stream
        uri = PB_STREAM+self.api_key
        try:
            websocket = yield from websockets.client.connect(uri)
        except:
            # If something goes wrong set connected False
            self.connected = False
            websocket = None
        if not websocket:
            return None

        # Listen forever
        while True:
            message = yield from websocket.recv()
            message = json.loads(message)

            # Handle message
            if message["type"] == "nop":
                self.last_nop = time.time()
            elif message["type"] == "push":
                self.last_nop = time.time()
                push = message["push"]
                if "notifications" in push.keys():
                    push = push["notifications"][0]
                self._get_latest_push(push)
                self.py3.update()
            elif message["type"] == "tickle" and message["subtype"] == "push":
                self.last_nop = time.time()
                self._get_latest_push()
                self.py3.update()

        # This won't be called, but to be safe
        yield from websocket.close()

if __name__ == "__main__":
    """
    Test this module by calling it directly.
    """
    from time import sleep
    x = Py3status()
    config = {
        'color_bad': '#FF0000',
        'color_degraded': '#FFFF00',
        'color_good': '#00FF00'
    }
    while True:
        print(x.update([], config))
        sleep(1)
