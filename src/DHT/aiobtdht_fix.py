"""
Monkey patches for aiobtdht bugs:

1. KeyError in routing_table/bucket.py Bucket.add:
   When removing nodes with negative rate, the code tries to pop a tuple (node, stat)
   from the _nodes dictionary, but the dictionary keys are just node objects.
   Fix: Extract the node object from the tuple before popping.

2. Invalid addr in dht.py _refresh_nodes:
   enum_nodes_for_refresh() returns bare addr tuples (host, port), but _refresh_nodes
   indexes with [1] expecting (node_id, addr) pairs, extracting just the port number.
   Fix: Use the addr directly instead of indexing with [1].
"""

import asyncio


def patch_aiobtdht():
    """Apply fixes to aiobtdht library bugs"""
    try:
        from aiobtdht.routing_table.bucket import Bucket
        from aiobtdht.routing_table.node_stat import NodeStat
        from aiobtdht import DHT

        # Fix 1: Bucket.add KeyError when deleting nodes
        def fixed_add(self, node):
            """Fixed version of Bucket.add that properly unpacks the tuple when deleting nodes"""
            if not self.id_in_range(node.id):
                raise IndexError("Node id not in bucket range")

            if node in self._nodes:
                self._nodes[node].renew()
                return True
            elif len(self._nodes) < self._max_capacity:
                self._nodes[node] = NodeStat()
                return True
            else:
                can_delete = list(filter(lambda it: it[1].rate < 0, self._enum_nodes()))
                if can_delete:
                    for node_to_delete, _ in can_delete:
                        self._nodes.pop(node_to_delete)

                    return self.add(node)
                else:
                    return False

        Bucket.add = fixed_add

        # Fix 2: _refresh_nodes passes port int instead of (host, port) tuple
        # enum_nodes_for_refresh() returns addr tuples directly, not (node_id, addr) pairs
        async def fixed_refresh_nodes(self):
            responses = filter(
                lambda response: response,
                await asyncio.gather(
                    *(self.remote_ping(addr) for addr in self.routing_table.enum_nodes_for_refresh())
                )
            )

            for addr, data in responses:
                self._add_node(node_id=data["id"], addr=addr)

        DHT._refresh_nodes = fixed_refresh_nodes

        return True

    except Exception as e:
        print(f"Warning: Failed to patch aiobtdht: {e}")
        return False


# Apply the patch when this module is imported
patch_aiobtdht()

