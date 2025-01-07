class BadAddress(ValueError):
    """Exception for bad address response"""
    def __init__(self, address):
        super().__init__(f"Bad address: `{address}`")
        self.address = address
