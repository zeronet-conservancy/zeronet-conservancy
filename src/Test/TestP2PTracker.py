from P2P.discovery.tracker import getAddressParts, TrackerStats


class TestP2PTracker:
    def testGetAddressPartsHttp(self):
        parts = getAddressParts("http://tracker.example.com:8080")
        assert parts == {
            "protocol": "http",
            "address": "tracker.example.com:8080",
            "ip": "tracker.example.com",
            "port": "8080",
        }

    def testGetAddressPartsHttpsDefaultPort(self):
        parts = getAddressParts("https://tracker.example.com")
        assert parts["port"] == 443
        assert parts["ip"] == "tracker.example.com"

    def testGetAddressPartsInvalid(self):
        assert getAddressParts("not a tracker") is None
        assert getAddressParts("tracker.example.com") is None  # no ://

    def testReliableByDefault(self):
        stats = TrackerStats()
        assert stats.isReliable("http://t.example.com") is True

    def testUnreliableAfterRepeatedErrors(self):
        stats = TrackerStats()
        tracker = "http://flaky.example.com"
        for _ in range(6):
            stats.recordRequest(tracker)
            stats.recordError(tracker, Exception("timeout"))
        assert stats.isReliable(tracker) is False
        # force=True bypasses the backoff
        assert stats.isReliable(tracker, force=True) is True

    def testSuccessResetsErrorCount(self):
        stats = TrackerStats()
        tracker = "http://recovering.example.com"
        for _ in range(6):
            stats.recordRequest(tracker)
            stats.recordError(tracker, Exception("timeout"))
        assert stats.isReliable(tracker) is False

        stats.recordSuccess(tracker)
        assert stats.get(tracker)["num_error"] == 0
        assert stats.isReliable(tracker) is True

    def testErrorNotCountedWithoutInternet(self):
        stats = TrackerStats()
        tracker = "http://t.example.com"
        for _ in range(10):
            stats.recordRequest(tracker)
            stats.recordError(tracker, Exception("no route"), has_internet=False)
        assert stats.get(tracker)["num_error"] == 0
        assert stats.isReliable(tracker) is True
