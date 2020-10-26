import random
import time
import os
import logging
import json
import atexit
import re

import gevent

from Config import config
from Plugin import PluginManager
from util import helper


class TrackerStorage(object):
    def __init__(self):
        self.site_announcer = None
        self.log = logging.getLogger("TrackerStorage")

        self.working_tracker_time_interval = 60 * 60
        self.tracker_down_time_interval = 60 * 60
        self.tracker_discover_time_interval = 5 * 60

        self.shared_trackers_limit_per_protocol = {}
        self.shared_trackers_limit_per_protocol["other"] = 2

        self.file_path = "%s/shared-trackers.json" % config.data_dir
        self.load()
        self.time_discover = 0.0
        self.time_success = 0.0
        atexit.register(self.save)

    def initTrackerLimitForProtocol(self):
        for s in re.split("[,;]", config.shared_trackers_limit_per_protocol):
            x = s.split("=", 1)
            if len(x) == 1:
                x = ["other", x[0]]
            try:
                self.shared_trackers_limit_per_protocol[x[0]] = int(x[1])
            except ValueError:
                pass
        self.log.info("Limits per protocol: %s" % self.shared_trackers_limit_per_protocol)

    def getTrackerLimitForProtocol(self, protocol):
        l = self.shared_trackers_limit_per_protocol
        return l.get(protocol, l.get("other"))

    def setSiteAnnouncer(self, site_announcer):
        if not site_announcer:
            return

        if not self.site_announcer:
            self.site_announcer = site_announcer
            self.initTrackerLimitForProtocol()
            self.recheckValidTrackers()
        else:
            self.site_announcer = site_announcer

    def isTrackerAddressValid(self, tracker_address):
        if not self.site_announcer: # Not completely initialized, skip check
            return True

        address_parts = self.site_announcer.getAddressParts(tracker_address)
        if not address_parts:
            self.log.debug("Invalid tracker address: %s" % tracker_address)
            return False

        handler = self.site_announcer.getTrackerHandler(address_parts["protocol"])
        if not handler:
            self.log.debug("Invalid tracker address: Unknown protocol %s: %s" % (address_parts["protocol"], tracker_address))
            return False

        return True

    def recheckValidTrackers(self):
        trackers = self.getTrackers()
        for address, tracker in list(trackers.items()):
            if not self.isTrackerAddressValid(address):
                del trackers[address]

    def isUdpEnabled(self):
        if config.disable_udp:
            return False

        if config.trackers_proxy != "disable":
            return False

        if config.tor == "always":
            return False

        return True

    def getNormalizedTrackerProtocol(self, tracker_address):
        if not self.site_announcer:
            return None

        address_parts = self.site_announcer.getAddressParts(tracker_address)
        if not address_parts:
            return None

        protocol = address_parts["protocol"]
        if protocol == "https":
            protocol = "http"

        return protocol

    def deleteUnusedTrackers(self, supported_trackers):
        # If a tracker is in our list, but is absent from the results of getSupportedTrackers(),
        # it seems to be supported by software, but forbidden by the settings or network configuration.
        # We check and remove thoose trackers here, since onTrackerError() is never emitted for them.
        trackers = self.getTrackers()
        for tracker_address, tracker in list(trackers.items()):
            t = max(trackers[tracker_address]["time_added"],
                    trackers[tracker_address]["time_success"])
            if tracker_address not in supported_trackers and t < time.time() - self.tracker_down_time_interval:
                self.log.info("Tracker %s looks unused, removing." % tracker_address)
                del trackers[tracker_address]

    def getSupportedProtocols(self):
        if not self.site_announcer:
            return None

        supported_trackers = self.site_announcer.getSupportedTrackers()

        self.deleteUnusedTrackers(supported_trackers)

        protocols = set()
        for tracker_address in supported_trackers:
            protocol = self.getNormalizedTrackerProtocol(tracker_address)
            if not protocol:
                continue
            if protocol == "udp" and not self.isUdpEnabled():
                continue
            protocols.add(protocol)

        protocols = list(protocols)

        self.log.debug("Supported tracker protocols: %s" % protocols)

        return protocols

    def getDefaultFile(self):
        return {"trackers": {}}

    def onTrackerFound(self, tracker_address, my=False, persistent=False):
        if not self.isTrackerAddressValid(tracker_address):
            return False

        trackers = self.getTrackers()
        added = False
        if tracker_address not in trackers:
            # "My" trackers never get deleted on announce errors, but aren't saved between restarts.
            # They are to be used as automatically added addresses from the Bootstrap plugin.
            # Persistent trackers never get deleted.
            # They are to be used for entries manually added by the user.
            trackers[tracker_address] = {
                "time_added": time.time(),
                "time_success": 0,
                "latency": 99.0,
                "num_error": 0,
                "my": False,
                "persistent": False
            }
            self.log.info("New tracker found: %s" % tracker_address)
            added = True

        trackers[tracker_address]["time_found"] = time.time()
        trackers[tracker_address]["my"] |= my
        trackers[tracker_address]["persistent"] |= persistent
        return added

    def onTrackerSuccess(self, tracker_address, latency):
        trackers = self.getTrackers()
        if tracker_address not in trackers:
            return False

        trackers[tracker_address]["latency"] = latency
        trackers[tracker_address]["time_success"] = time.time()
        trackers[tracker_address]["num_error"] = 0

        self.time_success = time.time()

    def onTrackerError(self, tracker_address):
        trackers = self.getTrackers()
        if tracker_address not in trackers:
            return False

        trackers[tracker_address]["time_error"] = time.time()
        trackers[tracker_address]["num_error"] += 1

        if trackers[tracker_address]["my"] or trackers[tracker_address]["persistent"]:
            return

        if self.time_success < time.time() - self.tracker_down_time_interval / 2:
            # Don't drop trackers from the list, if there haven't been any successful announces recently.
            # There may be network connectivity issues.
            return

        protocol = self.getNormalizedTrackerProtocol(tracker_address) or ""

        nr_working_trackers_for_protocol = len(self.getTrackersPerProtocol(working_only=True).get(protocol, []))
        nr_working_trackers = len(self.getWorkingTrackers())

        error_limit = 30
        if nr_working_trackers_for_protocol >= self.getTrackerLimitForProtocol(protocol):
            error_limit = 10
            if nr_working_trackers >= config.shared_trackers_limit:
                error_limit = 5

        if trackers[tracker_address]["num_error"] > error_limit and trackers[tracker_address]["time_success"] < time.time() - self.tracker_down_time_interval:
            self.log.info("Tracker %s looks down, removing." % tracker_address)
            del trackers[tracker_address]

    def isTrackerWorking(self, tracker_address):
        trackers = self.getTrackers()
        tracker = trackers[tracker_address]
        if not tracker:
            return False

        if tracker["time_success"] > time.time() - self.working_tracker_time_interval:
            return True

        return False

    def getTrackers(self):
        return self.file_content.setdefault("trackers", {})

    def getTrackersPerProtocol(self, working_only=False):
        if not self.site_announcer:
            return None

        trackers = self.getTrackers()

        trackers_per_protocol = {}
        for tracker_address in trackers:
            protocol = self.getNormalizedTrackerProtocol(tracker_address)
            if not protocol:
                continue
            if not working_only or self.isTrackerWorking(tracker_address):
                trackers_per_protocol.setdefault(protocol, []).append(tracker_address)

        return trackers_per_protocol

    def getWorkingTrackers(self):
        trackers = {
            key: tracker for key, tracker in self.getTrackers().items()
            if self.isTrackerWorking(key)
        }
        return trackers

    def getFileContent(self):
        if not os.path.isfile(self.file_path):
            open(self.file_path, "w").write("{}")
            return self.getDefaultFile()
        try:
            return json.load(open(self.file_path))
        except Exception as err:
            self.log.error("Error loading trackers list: %s" % err)
            return self.getDefaultFile()

    def load(self):
        self.file_content = self.getFileContent()

        trackers = self.getTrackers()
        self.log.debug("Loaded %s shared trackers" % len(trackers))
        for address, tracker in list(trackers.items()):
            tracker.setdefault("time_added", time.time())
            tracker.setdefault("time_success", 0)
            tracker.setdefault("latency", 99.0)
            tracker.setdefault("my", False)
            tracker.setdefault("persistent", False)
            tracker["num_error"] = 0
            if tracker["my"]:
                del trackers[address]
        self.recheckValidTrackers()

    def save(self):
        s = time.time()
        helper.atomicWrite(self.file_path, json.dumps(self.file_content, indent=2, sort_keys=True).encode("utf8"))
        self.log.debug("Saved in %.3fs" % (time.time() - s))

    def enoughWorkingTrackers(self):
        supported_protocols = self.getSupportedProtocols()
        if not supported_protocols:
            return False

        trackers_per_protocol = self.getTrackersPerProtocol(working_only=True)
        if not trackers_per_protocol:
            return False

        unmet_conditions = 0

        total_nr = 0

        for protocol in supported_protocols:
            trackers = trackers_per_protocol.get(protocol, [])
            if len(trackers) < self.getTrackerLimitForProtocol(protocol):
                self.log.info("Not enough working trackers for protocol %s: %s < %s" % (
                    protocol, len(trackers), self.getTrackerLimitForProtocol(protocol)))
                unmet_conditions += 1
            total_nr += len(trackers)

        if total_nr < config.shared_trackers_limit:
            self.log.info("Not enough working trackers (total): %s < %s" % (
                total_nr, config.shared_trackers_limit))
            unmet_conditions + 1

        return unmet_conditions == 0

    def discoverTrackers(self, peers):
        if self.enoughWorkingTrackers():
            return False

        self.log.info("Discovering trackers from %s peers..." % len(peers))

        s = time.time()
        num_success = 0
        num_trackers_discovered = 0
        for peer in peers:
            if peer.connection and peer.connection.handshake.get("rev", 0) < 3560:
                continue  # Not supported

            res = peer.request("getTrackers")
            if not res or "error" in res:
                continue

            num_success += 1

            random.shuffle(res["trackers"])
            for tracker_address in res["trackers"]:
                if type(tracker_address) is bytes:  # Backward compatibilitys
                    tracker_address = tracker_address.decode("utf8")
                added = self.onTrackerFound(tracker_address)
                if added:  # Only add one tracker from one source
                    num_trackers_discovered += 1
                    break

        if not num_success and len(peers) < 20:
            self.time_discover = 0.0

        if num_success:
            self.save()

        self.log.info("Discovered %s new trackers from %s/%s peers in %.3fs" % (num_trackers_discovered, num_success, len(peers), time.time() - s))


if "tracker_storage" not in locals():
    tracker_storage = TrackerStorage()


@PluginManager.registerTo("SiteAnnouncer")
class SiteAnnouncerPlugin(object):
    def getTrackers(self):
        tracker_storage.setSiteAnnouncer(self)
        if tracker_storage.time_discover < time.time() - tracker_storage.tracker_discover_time_interval:
            tracker_storage.time_discover = time.time()
            gevent.spawn(tracker_storage.discoverTrackers, self.site.getConnectedPeers())
        trackers = super(SiteAnnouncerPlugin, self).getTrackers()
        shared_trackers = list(tracker_storage.getTrackers().keys())
        if shared_trackers:
            return trackers + shared_trackers
        else:
            return trackers

    def announceTracker(self, tracker, *args, **kwargs):
        tracker_storage.setSiteAnnouncer(self)
        res = super(SiteAnnouncerPlugin, self).announceTracker(tracker, *args, **kwargs)
        if res:
            latency = res
            tracker_storage.onTrackerSuccess(tracker, latency)
        elif res is False:
            tracker_storage.onTrackerError(tracker)

        return res


@PluginManager.registerTo("FileRequest")
class FileRequestPlugin(object):
    def actionGetTrackers(self, params):
        shared_trackers = list(tracker_storage.getWorkingTrackers().keys())
        random.shuffle(shared_trackers)
        self.response({"trackers": shared_trackers})


@PluginManager.registerTo("ConfigPlugin")
class ConfigPlugin(object):
    def createArguments(self):
        group = self.parser.add_argument_group("TrackerShare plugin")
        group.add_argument('--shared_trackers_limit', help='Discover new shared trackers if this number of shared trackers isn\'t reached (total)', default=20, type=int, metavar='limit')
        group.add_argument('--shared_trackers_limit_per_protocol', help='Discover new shared trackers if this number of shared trackers isn\'t reached per each supported protocol', default="zero=10,other=5", metavar='limit')

        return super(ConfigPlugin, self).createArguments()
