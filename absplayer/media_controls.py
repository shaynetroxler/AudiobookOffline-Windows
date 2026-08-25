from __future__ import annotations


class MediaControls:
    """Windows equivalent of the Linux app's MPRIS service (lock screen /
    Action Center / media-key integration via System Media Transport
    Controls). Same constructor and call shape as the Linux MprisService so
    PlayerPage/MainWindow don't need to know which platform they're on.

    Not implemented yet: real SMTC requires ISystemMediaTransportControlsInterop.GetForWindow,
    a COM interop call that Python's WinRT projection (winsdk) doesn't expose
    directly -- it needs hand-written ctypes/COM plumbing. Stubbed as a no-op
    for now so the rest of the app works; lock-screen controls are a planned
    follow-up, not a Windows quirk to design around.
    """

    def __init__(self, get_status, get_metadata, get_position_us, actions):
        self._get_status = get_status
        self._get_metadata = get_metadata
        self._get_position_us = get_position_us
        self._actions = actions

    def notify(self):
        pass

    def seeked(self, position_us):
        pass
