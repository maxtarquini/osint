"""Safe capability registry failures and cancellation signals."""


class CapabilityError(Exception):
    """A safe, operator-facing capability validation or persistence error."""


class CapabilityCancelled(CapabilityError):
    pass
