"""What every connector has to provide.

A connector mirrors a note into a real app. It is never load-bearing: the note
is already saved locally before any connector is asked to do anything, so a
missing token, a dead network or a broken server degrades to "the note is still
on your disk" rather than losing it.
"""

from dataclasses import dataclass


@dataclass
class Delivery:
    ok: bool
    detail: str = ""


class Connector:
    #: Shown in the patch bay.
    type_name = "connector"

    #: Whether turning this on means Sayso starts talking to the network.
    #: Surfaced in the dashboard, because "works offline" stops being true the
    #: moment a hosted connector is switched on and the user deserves to see
    #: exactly which ones cost that.
    requires_network = False

    def __init__(self, name, config):
        self.name = name
        self.config = config or {}
        self.enabled = bool(self.config.get("enabled"))
        self.last_error = ""

    @property
    def is_configured(self):
        """True when this connector has everything it needs to send."""
        raise NotImplementedError

    @property
    def needs(self):
        """Plain-English description of what is still missing, or ''."""
        return "" if self.is_configured else "not set up"

    def send_note(self, text):
        raise NotImplementedError

    def state(self):
        if not self.enabled:
            return "off"
        if not self.is_configured:
            return "needs setup"
        return "error" if self.last_error else "connected"

    def describe(self):
        return {
            "name": self.name,
            "type": self.type_name,
            "enabled": self.enabled,
            "configured": self.is_configured,
            "state": self.state(),
            "needs": self.needs,
            "error": self.last_error,
            "requires_network": bool(
                self.config.get("requires_network", self.requires_network)
            ),
            # Subclasses list what the dashboard should offer to edit. Secrets
            # are declared here but their values never are.
            "fields": [],
        }
