from P2P.RequestAccessRelay import RequestAccessRelay


class TestP2PRequestAccessRelay:
    def testAddAndGetAllRoundTrips(self):
        relay = RequestAccessRelay()
        relay.add("1SiteAAAAAAAAAAAAAAAAAAAAAAA", "1RequesterAAAAAAAAAAAAAAAAA", "sig1")
        entries = relay.getAll("1SiteAAAAAAAAAAAAAAAAAAAAAAA")
        assert entries["1RequesterAAAAAAAAAAAAAAAAA"]["signature"] == "sig1"

    def testGetAllReturnsEmptyForUnknownSite(self):
        relay = RequestAccessRelay()
        assert relay.getAll("1UnknownSiteAAAAAAAAAAAAAAAA") == {}

    def testRemoveDropsEntry(self):
        relay = RequestAccessRelay()
        relay.add("1SiteAAAAAAAAAAAAAAAAAAAAAAA", "1RequesterAAAAAAAAAAAAAAAAA", "sig1")
        relay.remove("1SiteAAAAAAAAAAAAAAAAAAAAAAA", "1RequesterAAAAAAAAAAAAAAAAA")
        assert relay.getAll("1SiteAAAAAAAAAAAAAAAAAAAAAAA") == {}

    def testPerSiteCapEvictsOldestFirst(self):
        relay = RequestAccessRelay(max_per_site=3, max_total=100)
        for i in range(5):
            relay.add("1SiteAAAAAAAAAAAAAAAAAAAAAAA", "requester%d" % i, "sig%d" % i)
        entries = relay.getAll("1SiteAAAAAAAAAAAAAAAAAAAAAAA")
        assert len(entries) == 3
        # The two oldest (0, 1) were evicted; the three freshest remain.
        assert set(entries.keys()) == {"requester2", "requester3", "requester4"}

    def testGlobalCapEvictsAcrossSites(self):
        relay = RequestAccessRelay(max_per_site=10, max_total=4)
        for site_i in range(2):
            for req_i in range(3):
                relay.add("site%d" % site_i, "requester%d" % req_i, "sig")
        total = sum(len(relay.getAll("site%d" % i)) for i in range(2))
        assert total == 4

    def testTtlExpiresOldEntries(self):
        relay = RequestAccessRelay(ttl=0)  # immediately expired on next read
        relay.add("1SiteAAAAAAAAAAAAAAAAAAAAAAA", "1RequesterAAAAAAAAAAAAAAAAA", "sig1")
        assert relay.getAll("1SiteAAAAAAAAAAAAAAAAAAAAAAA") == {}

    def testReAddRefreshesEntryWithoutDuplication(self):
        relay = RequestAccessRelay(max_per_site=3, max_total=100)
        relay.add("1SiteAAAAAAAAAAAAAAAAAAAAAAA", "1RequesterAAAAAAAAAAAAAAAAA", "sig1")
        relay.add("1SiteAAAAAAAAAAAAAAAAAAAAAAA", "1RequesterAAAAAAAAAAAAAAAAA", "sig2")
        entries = relay.getAll("1SiteAAAAAAAAAAAAAAAAAAAAAAA")
        assert len(entries) == 1
        assert entries["1RequesterAAAAAAAAAAAAAAAAA"]["signature"] == "sig2"
