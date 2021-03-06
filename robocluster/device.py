"""Message passing for robocluster."""

import asyncio
from collections import defaultdict
from contextlib import suppress
from fnmatch import fnmatch
from functools import wraps
from threading import Thread

from .net import Socket, key_to_multicast
from .util import duration_to_seconds, as_coroutine
from .serial import SerialDevice


class Device:
    """A device to interact with the robocluster network."""

    transport = 'json'

    def __init__(self, name, group, loop=None):
        """Initialize the device."""
        self.name = name
        self.events = defaultdict(list)

        address = key_to_multicast(group)

        self._thread = None
        self._loop = loop if loop else asyncio.new_event_loop()

        self._sender = Socket(
            address,
            transport=self.transport,
            loop=self._loop
        )
        self._send_queue = asyncio.Queue(loop=self._loop)

        self._receiver = Socket(
            address,
            transport=self.transport,
            loop=self._loop
        )
        self._receiver.bind()

        self._serial_devices = {}

    def publish(self, topic, data):
        """Publish to topic."""
        packet = {
            'event': '{}/{}'.format(self.name, topic),
            'data': data,
        }
        return self._send_queue.put(packet)

    def on(self, event):
        """Add a callback for an event."""
        def _decorator(callback):
            coro = as_coroutine(callback)
            self.events[event].append(coro)
            return callback
        return _decorator

    def task(self, task):
        """Create a background task."""
        coro = as_coroutine(task)
        self._loop.create_task(coro())
        return task

    def every(self, duration):
        """Create a background task that runs every duration."""
        def _decorator(func):
            @wraps(func)
            async def _wrapper():
                while True:
                    coro = as_coroutine(func)
                    await coro()
                    await self.sleep(duration)
            self.task(_wrapper)
            return func
        return _decorator

    def sleep(self, duration):
        """Sleep the device."""
        seconds = duration_to_seconds(duration)
        return asyncio.sleep(seconds, loop=self._loop)

    async def _send_task(self):
        """Send packets in the send queue."""
        while True:
            packet = await self._send_queue.get()
            await self._sender.send(packet)

    async def _receive_task(self):
        """Recieve packets and call the appropriate callbacks."""
        while True:
            packet, _ = await self._receiver.receive()
            event, data = packet['event'], packet['data']
            for key, callbacks in self.events.items():
                if not fnmatch(event, key):
                    continue
                for callback in callbacks:
                    self._loop.create_task(callback(event, data))

    async def _serial_read_task(self, serial_device):
        """Handle callbacks for a serial_device."""
        async with serial_device as ser:
            while True:
                packet = await ser.read_packet()
                event, data = packet['event'], packet['data']
                if event in ser.events:
                    for callback in ser.events[event]:
                        self._loop.create_task(callback(event, data))

    def link_serial(self, serial_device):
        """Link an existing serial device into the event loop."""
        serial_device._loop = self._loop
        self._serial_devices[serial_device.usb_path] = serial_device

    def create_serial(self, usb_path, encoding='json'):
        """Create a new SerialDevice."""
        self._serial_devices[usb_path] = SerialDevice(
            usb_path,
            encoding=encoding,
            loop=self._loop,
        )
        return self._serial_devices[usb_path]

    def start(self):
        """Start device."""
        if self._thread:
            raise RuntimeError('device already running')
        self._thread = Thread(target=self._thread_target)
        self._thread.start()

    def _thread_target(self):
        """Target for thread to run event loop in background."""
        loop = self._loop
        asyncio.set_event_loop(loop)

        loop.create_task(self._send_task())
        loop.create_task(self._receive_task())
        for serial_device in self._serial_devices.values():
            self._loop.create_task(self._serial_read_task(serial_device))
        loop.run_forever()

        for task in asyncio.Task.all_tasks(loop=loop):
            task.cancel()
            with suppress(asyncio.CancelledError):
                loop.run_until_complete(task)

    def run(self):
        """Run device in foreground."""
        try:
            self.start()
            self.wait()
        except KeyboardInterrupt:
            self.stop()
            raise

    def wait(self):
        """Wait until device exits."""
        if self._thread:
            self._thread.join()

    def stop(self):
        """Stop running device."""
        if not self._thread:
            raise RuntimeError('device not running')
        self._loop.call_soon_threadsafe(self._loop.stop)
        self._thread.join()
        self._thread = None
