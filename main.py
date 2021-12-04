#!/usr/bin/env python3

import pyslinger as irslinger
import sys
import asyncio
import os
import re
import signal
import time
import logging as log

log.basicConfig(level=log.DEBUG)


from meross_iot.http_api import MerossHttpClient
from meross_iot.manager import MerossManager

EMAIL = os.environ.get('MEROSS_EMAIL') or "YOUR_MEROSS_CLOUD_EMAIL"
PASSWORD = os.environ.get('MEROSS_PASSWORD') or "YOUR_MEROSS_CLOUD_PASSWORD"

SHUTDOWN = 60*10
GPIO_PIN = 24
PROTOCOL = "RC-5"
pm6006 = {"off": "11010000001100", "on": "11010000001100x11010000001100",
		  "mute": "11010000001101", "up": "11010000010000", "down": "11010000010001", "output": "11010000011101",
		  "direct": "11010000100010", "loudness": "11010000110010", "cd": "11010100111111", "tuner": "11010001111111",
		  "phono": "11010101111111", "recorder": "11011010111111", "coax": "11010000x000001011001",
		  "opt": "11010000x000001101000", "net": "11011001x111111001010"}


def sigterm_handler(_signo, _stack_frame):
	# Raises SystemExit(0):
	sys.exit(0)


def send_ir(code: str):
	ir = irslinger.IR(GPIO_PIN, PROTOCOL, dict())
	if pm6006.get(code):
		ir.send_code(pm6006[code])
	else:
		log.info("Code not found")
	log.info("Exiting IR")


async def init_meross():
	# Setup the HTTP client API from user-password
	http_api_client = await MerossHttpClient.async_from_user_password(email=EMAIL, password=PASSWORD)

	# Setup and start the device manager
	manager = MerossManager(http_client=http_api_client)
	await manager.async_init()

	# Retrieve all the MSS310 devices that are registered on this account
	await manager.async_device_discovery()
	plugs = manager.find_devices(device_type="mss310")

	if len(plugs) < 1:
		log.info("No MSS310 plugs found...")
	else:
		# Turn it on channel 0
		# Note that channel argument is optional for MSS310 as they only have one channel
		dev = None
		for d in plugs:
			if d.name == "pm6006":
				dev = d
				break
		# The first time we play with a device, we must update its status
		await dev.async_update()
		log.info(dev)

		return manager, http_api_client, dev


def is_line_in_file():
	file = open("/proc/asound/card1/pcm0p/sub0/status", "r")
	for line in file:
		if re.search("state: RUNNING", line):
			return True
	return False


async def main():
	manager, http_api_client, dev = await init_meross()
	metrics = await dev.async_get_instant_metrics()
	stop_time = None
	is_playing = is_line_in_file()
	amp_state = False if (metrics.power < 10.0) else True
	try:
		while True:
			log.debug("Run Loop")
			await asyncio.sleep(2)
			if is_line_in_file():
				log.debug("alsa playback is running")
				if is_playing is False:
					log.info("Playback started")
					is_playing = True
					amp_state = True
					stop_time = None
					metrics = await dev.async_get_instant_metrics()
					if metrics.power < 10.0:
						log.info("Power on AMP")
						send_ir("on")
					else:
						log.info("AMP already started")
			elif amp_state is False:
				log.debug("AMP is off")
				continue
			elif stop_time is None:
				log.info("Music paused init shutdown counter")
				stop_time = time.time()
				is_playing = False
			elif time.time() - stop_time > SHUTDOWN:
				log.info("Timeout reached power off AMP")
				stop_time = None
				is_playing = False
				amp_state = False
				metrics = await dev.async_get_instant_metrics()
				if metrics.power > 10.0:
					send_ir("off")
				else:
					log.info("AMP already off")
			else:
				shutdown = round(SHUTDOWN - (time.time() - stop_time))
				log.info("Music paused. Time until shutdown: " + str(shutdown))
				is_playing = False

	finally:
		log.info("shutdown meross connection")
		manager.close()
		await http_api_client.async_logout()


# Simply define the GPIO pin, protreceiverocol (NEC, RC-5 or RAW) and
# override the protocol defaults with the dictionary if required.
# Provide the IR code to the send_code() method.
if __name__ == "__main__":
	signal.signal(signal.SIGTERM, sigterm_handler)
	signal.signal(signal.SIGINT, sigterm_handler)
	if sys.argv[1] == "run":
		loop = asyncio.get_event_loop()
		loop.run_until_complete(main())
		loop.close()
	else:
		send_ir(sys.argv[1])
