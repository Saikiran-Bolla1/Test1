class DTCInfo:
    """
    Represents a Diagnostic Trouble Code (DTC) and its status.
    """
    def __init__(self, DTC, status=None):
        self.DTC = str(DTC).lower()
        self.status = status

    def __eq__(self, other):
        if not isinstance(other, DTCInfo):
            return False
        return self.DTC == other.DTC and self.status == other.status

    def __hash__(self):
        return hash((self.DTC, self.status))

    def __repr__(self):
        return f"DTCInfo(DTC={self.DTC}, status={self.status})"