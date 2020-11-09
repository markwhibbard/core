import asyncio
import random
import time
from datetime import datetime
import json


class SmartVidHub:

    def __init__(self, hass, topic):
        self._name = topic  #TODO is this what I want?
        self._topic = topic
        self._hass = hass
        self._discovereddevices=[]
        self._devices = []
        #self._id = host.lower()  #figure this out later

    async def discover(self):
        #TODO handle case when smartvid server is not up when discovery is being done
        #TODO handle when we perform discovery and there are already devices in self.devices

        self._discovereddevices=[]
        self.devices = []
        self._hass.components.mqtt.async_publish(self._topic+'/discover', None)        
        timeout = 5
        starttime = time.time()
        while time.time() < starttime + timeout:
            await asyncio.sleep(0.1)
            if len(self._discovereddevices) > 0:
#                print(self._discovereddevices)
                for device in self._discovereddevices:
#                    print(device)
                    self.devices.append(
                        SmartVidDevice(
                            device['camera_id'],
                            device['feedurl'],
                            self
                        ))
                return True

        print("SmartVid Error: Timeout on device discovery")
        return False

    def refresh(self):
        self._hass.components.mqtt.async_publish(self._topic+'/refresh', None)

    #TODO make async
    async def connect(self):

        def message_received(topic, payload, qos):

            uid=topic.split(self._topic + "/")[1]
            thisdevice=None
            if uid=="devices":
                self._discovereddevices = json.loads(payload)
                print("Discovered {} smartvid devices:".format(len(self._discovereddevices)))
                return


            for device in self.devices:
                if device.uid==uid:
                    thisdevice=device
            if thisdevice is None and uid != "discover":
                print("Error in SmartVid hub: didn't find device with uid {} loaded".format(uid))
                print("Loaded: {}".format(self.devices))
                print("Rediscover devices")
                #asyncio.run(self.discover())
                #TODO handle this command if discover successful
                return 

            """A new MQTT message has been received."""
            if len(payload) == 0:
                print("Error in SmartVid detector: No arguments in received status")
            else:
                args = json.loads(payload)
                if 'alert' in args.keys():
                    thisdevice._alertvalue = args['value']
                    #thisdevice._alerttimestamp = datetime.now().strftime("%Y.%m.%d %H:%M:%S")

                if 'face' in args.keys():
                    thisdevice._facename = args['name']
                    thisdevice._facetimestamp = datetime.now().strftime("%Y.%m.%d %H:%M:%S")

                thisdevice.publish_updates()
            
        await self._hass.components.mqtt.async_subscribe(self._topic + "/#", message_received)
        self._is_connected = True
        return True




class SmartVidDevice:

    def __init__(self, uid, feed, hub):
        """Init dummy roller."""
        self._uid = uid
        self.hub = hub
        self._name = uid
        self._feed = feed
        self._callbacks = set()

        self._alertvalue = 0
        #self._alerttimestamp = 0
        self._facename = ""
        self._facetimestamp = 0

    @property
    def feed(self):
        """Return ID for roller."""
        return self._feed
        
    @property
    def alertvalue(self):
        """Return ID for roller."""
        return self._alertvalue
        
    @property
    def facedetected(self):
        """Return ID for roller."""
        return self._facetimestamp
    @property
    def facename(self):
        """Return ID for roller."""
        return self._facename

    @property
    def uid(self):
        """Return ID for roller."""
        return self._uid

    @property
    def is_connected(self):
        """Return ID for roller."""
        return self.hub._is_connected
    @property
    def name(self):
        """Return ID for roller."""
        return self._name

    def register_callback(self, callback):
        """Register callback, called when Roller changes state."""
        self._callbacks.add(callback)

    def remove_callback(self, callback):
        """Remove previously registered callback."""
        self._callbacks.discard(callback)

    def update(self):
        self.hub.refresh()

    # In a real implementation, this library would call it's call backs when it was
    # notified of any state changeds for the relevant device.
    def publish_updates(self)->None:
        """Schedule call all registered callbacks."""
        for callback in self._callbacks:
            callback()
