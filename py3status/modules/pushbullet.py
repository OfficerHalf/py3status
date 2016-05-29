# -*- coding: utf-8 -*-
"""
Show the latest notification from Pushbullet.

Uses asyncio and websockets to show the latest notification from Pushbullet.
Clicking on the module will show the complete message using notify-send.

Configuration parameters:
    api_key: Your Pushbullet API token. This *MUST* be set for the module to
        work. Retrieve from https://www.pushbullet.com/#settings (default None)
    color: The output color when there is no notification to display.
        (default "#FFFFFF")
    format: The output when there is a notification to display. See
        placeholders below. (default ": {msg}")
    format_none: What is displayed when there is no notification to display.
        (default "")
    max_len: How many characters to display when using the {msg} placeholder.
        Set to 0 to set no maximum. (default 20)
    timeout: How long the latest push should be shown. If 0, the notifications
        in the bar will never expire. May not function properly if less than
        cache_timeout. (default 0)

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
    # Available configuration parameters
    api_key = None
    color = "#FFFFFF"
    format = "  {msg}"
    format_none = ""
    max_len = 20
    timeout = 0

    def __init__(self, api_key=None):
        self.clicked = True
        self.connected = False
        self.last_nop = 0
        self.last_push = None
        self.thread_started = False
        self.api_key = api_key

    def update(self, i3s_output_list, i3s_config):
        """Py3status calls this function."""
        # Start the worker thread if it isn't running and an api key is set
        if not self.thread_started and self.api_key:
            t = Thread(target=self._start_listen)
            t.daemon = True
            t.start()
            self.thread_started = True
        # Create the output text
        status = self._get_status()
        color = self._get_color(i3s_config, status)
        response = {
            'cached_until': self.py3.CACHE_FOREVER,
            'color': color,
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

    """
    * MAIN THREAD METHODS *
    """
    def _get_status(self):
        """Get the full text for the module."""
        status = self.format_none
        if self.last_push and not self.clicked:
            diff = time.time() - self.last_push["time"]
            if self.timeout > 0 and diff > self.timeout:
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
        if not self.api_key:
            status += " No API key set."
        return status

    def _get_color(self, cfg, status):
        """Set the color for update.

        color_bad: not received a nop in 60 seconds or are not connected
        color_degraded: connected, but no nop in 30 seconds
        color_good: have seen a push/nop
        """
        if self.connected:
            color = cfg["color_good"]
            diff = time.time() - self.last_nop
            if diff > 60:
                color = cfg["color_bad"]
            elif diff > 30:
                color = cfg["color_degraded"]
            elif status == self.format_none:
                color = self.color
        else:
            color = cfg["color_bad"]
        return color

    """
    * WORKER THREAD METHODS *
    """
    def _start_listen(self):
        """Create event loop and run until the websocket dies"""
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        loop.run_until_complete(self._listen())
        self.thread_started = False

    @asyncio.coroutine
    def _listen(self):
        """Create websocket, listen until we hear nothing for 30 seconds."""
        # Connect to PB stream
        uri = PB_STREAM+self.api_key
        websocket = yield from websockets.client.connect(uri)
        self.connected = True

        # Listen until no message is received for 30 seconds
        while True:
            try:
                message = yield from asyncio.wait_for(
                    self._recv_message(websocket), 31)
            except asyncio.TimeoutError:
                self.connected = False
                break
            self._process_message(message)

        # This means the socket died/was never alive. Will try to reconnect.
        yield from websocket.close()
        # Update so we can set the color to color_bad until we get some response
        self.py3.update()

    @staticmethod
    @asyncio.coroutine
    def _recv_message(websocket):
        message = yield from websocket.recv()
        return message

    def _process_message(self, message):
        """Decides what to do based on message type"""
        # Translate the json string to a dictionary
        message = json.loads(message)

        """Message Types:
            nop - keep-alive message, sent every 30 seconds
            push - a regular push notification/notification
            tickle - there was some other type of push, likely sent by
                     pushbullet itself (if subtype is push)
        """
        if message["type"] == "nop":
            self.last_nop = time.time()
            self.py3.update()
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

    def _get_latest_push(self, push=None):
        """Queries latest push if needed, then sets self.last_push"""
        if not push:
            payload = {"limit": "1", "active": "true"}
            r = requests.get(PB_PUSHES, auth=(self.api_key, ""), params=payload)
            push = r.json()["pushes"][0]
        # This is a notification dismissal, we should just clear the status
        if "type" in push.keys() and push["type"] == "dismissal":
            self.clicked = True
        else:
            title = None
            body = None
            if "title" in push.keys():
                title = push["title"]
            if "body" in push.keys():
                body = push["body"]
            self.last_push = {"body": body, "title": title, "time": time.time()}
            self.clicked = False


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
