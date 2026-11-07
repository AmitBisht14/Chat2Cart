from chat2cart.config import Settings
from chat2cart.notify.base import Channel, Notify, notifier_for
from chat2cart.notify.log_channel import LogChannel
from chat2cart.notify.macos import MacosChannel

CHANNELS: dict[str, Channel] = {"macos": MacosChannel(), "log": LogChannel()}


def notify_from_settings(settings: Settings) -> Notify:
    """The notify function for the channel chosen in config (CHAT2CART_NOTIFY_CHANNEL)."""
    return notifier_for(CHANNELS[settings.notify_channel])
