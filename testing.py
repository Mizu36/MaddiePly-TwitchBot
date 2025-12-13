"""Utility helpers for simulating EventSub payloads inside the GUI tools tab.

Each coroutine in this module mirrors one of the EventSub listeners declared in
`twitchbot.CommandHandler`. The helpers build lightweight stand-ins for the
payload objects that TwitchIO would normally supply and then call the existing
listener so you can verify behaviour without waiting on a real webhook event.

No code runs automatically on import; GUI buttons (or manual REPL calls) should
`await testing.test_<event_name>(**overrides)` to exercise the desired path.
"""

from __future__ import annotations

from datetime import datetime, timezone
from random import randint
from types import SimpleNamespace
from typing import Any, Callable, TYPE_CHECKING

from tools import debug_print, get_reference

if TYPE_CHECKING:  # pragma: no cover
    from twitchbot import CommandHandler


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _ns(**kwargs: Any) -> SimpleNamespace:
    return SimpleNamespace(**kwargs)


_TRACKING_USER_IDS = ["user_tracking_1", "user_tracking_2", "user_tracking_3"]
_TRACKING_INDEX = 0


def _next_tracking_user_id() -> str:
    global _TRACKING_INDEX
    uid = _TRACKING_USER_IDS[_TRACKING_INDEX]
    _TRACKING_INDEX = (_TRACKING_INDEX + 1) % len(_TRACKING_USER_IDS)
    return uid


def _fake_user(
    *, display_name: str = "TestUser", user_id: str | None = None, login: str | None = None
) -> SimpleNamespace:
    username = login or display_name.lower()
    assigned_id = user_id or _next_tracking_user_id()
    return _ns(id=assigned_id, name=username, display_name=display_name)


class FakePartialUser(SimpleNamespace):
    """Minimal stand-in for twitchio.PartialUser used by GUI payload tests."""

    def __init__(
        self,
        *,
        display_name: str = "TestStreamer",
        user_id: str | None = None,
        login: str | None = None,
        channel_title: str = "Testing Stream",
        game_name: str = "Just Chatting",
    ) -> None:
        username = login or display_name.lower()
        assigned_id = user_id or _next_tracking_user_id()
        super().__init__(id=assigned_id, name=username, display_name=display_name)
        self.login = username
        self._channel_info = _ns(
            game_name=game_name,
            title=channel_title,
            broadcaster=_ns(id=assigned_id, name=username, display_name=display_name),
        )

    async def fetch_channel_info(self) -> SimpleNamespace:
        return self._channel_info

def _fake_broadcaster(
    display_name: str = "ModdiPly",
    *,
    user_id: str | None = None,
    login: str = "moddiply",
    channel_title: str = "Really cool test stream!",
    game_name: str = "Just Chatting",
) -> FakePartialUser:
    return FakePartialUser(
        display_name=display_name,
        user_id=user_id,
        login=login,
        channel_title=channel_title,
        game_name=game_name,
    )

def _fake_custom_reward(
    *,
    title: str = "Custom Reward",
    cost: int = 1000,
    prompt: str | None = "Custom prompt",
    is_user_input_required: bool = False,
) -> SimpleNamespace:
    return _ns(
        id=f"custom_reward_{randint(1000,9999)}",
        title=title,
        cost=cost,
        prompt=prompt,
        is_user_input_required=is_user_input_required,
        background_color="#9146FF",
        image=_ns(url_1x="https://static-cdn.jtvnw.net/default-1.png", url_2x="https://static-cdn.jtvnw.net/default-2.png", url_4x="https://static-cdn.jtvnw.net/default-4.png"),
    )

def _fake_default_reward(
    *,
    reward_type: str = "mystery-gift",
    channel_points: int = 100,
    prompt: str | None = "Auto reward prompt",
    is_user_input_required: bool = False,
    text: str | None = "This is a test of the default reward system.",
) -> SimpleNamespace:
    return _ns(
        id=f"default_reward_{randint(1000,9999)}",
        type=reward_type,
        prompt=prompt,
        text=text,
        channel_points=channel_points,
        is_user_input_required=is_user_input_required,
        default_image=_ns(url_1x="https://static-cdn.jtvnw.net/default-1.png", url_2x="https://static-cdn.jtvnw.net/default-2.png", url_4x="https://static-cdn.jtvnw.net/default-4.png"),
        background_color="#0E0E10",
    )

def _fake_message(text: str) -> SimpleNamespace:
    return _ns(text=text)

def _require_handler() -> "CommandHandler":
    handler = get_reference("CommandHandler")
    if handler is None:
        raise RuntimeError("CommandHandler reference not found; is the bot running?")
    return handler

def _build_payload(defaults: dict[str, Any], overrides: dict[str, Any]) -> SimpleNamespace:
    merged = defaults.copy()
    merged.update(overrides)
    return _ns(**merged)

class PayloadFactory:
    """Generates lightweight stand-ins for TwitchIO payload objects."""

    @staticmethod
    def chat_message(**overrides: Any) -> SimpleNamespace:
        chatter = overrides.pop("chatter", _fake_user())
        return _build_payload(
            {
                "chatter": chatter,
                "text": overrides.pop("text", "Hello from test payload!"),
                "timestamp": overrides.pop("timestamp", _now()),
                "channel": overrides.pop("channel", _ns(name="testchannel")),
            },
            overrides,
        )

    @staticmethod
    def channel_cheer(**overrides: Any) -> SimpleNamespace:
        user = overrides.pop("user", _fake_user(display_name="BitsUser"))
        return _build_payload(
            {
                "bits": overrides.pop("bits", 100),
                "user": user,
                "timestamp": overrides.pop("timestamp", _now()),
                "message": overrides.pop("message", _fake_message(f"{user.display_name} sent bits!")),
            },
            overrides,
        )

    @staticmethod
    def channel_subscribe(**overrides: Any) -> SimpleNamespace:
        return _build_payload(
            {
                "user": overrides.pop("user", _fake_user(display_name="FrankSub")),
                "gift": overrides.pop("gift", False),
                "tier": overrides.pop("tier", "1000"),
                "timestamp": overrides.pop("timestamp", _now()),
            },
            overrides,
        )

    @staticmethod
    def channel_subscribe_message(**overrides: Any) -> SimpleNamespace:
        return _build_payload(
            {
                "user": overrides.pop("user", _fake_user(display_name="FilianResub")),
                "streak_months": overrides.pop("streak_months", 3),
                "cumulative_months": overrides.pop("cumulative_months", 12),
                "text": overrides.pop("text", "Keepin' the streak alive"),
                "tier": overrides.pop("tier", "1000"),
                "months": overrides.pop("months", 1),
                "timestamp": overrides.pop("timestamp", _now()),
            },
            overrides,
        )

    @staticmethod
    def channel_subscription_end(**overrides: Any) -> SimpleNamespace:
        return _build_payload(
            {
                "user": overrides.pop("user", _fake_user(display_name="DepartingSub")),
                "is_gift": overrides.pop("is_gift", False),
            },
            overrides,
        )

    @staticmethod
    def channel_follow(**overrides: Any) -> SimpleNamespace:
        return _build_payload(
            {
                "user": overrides.pop("user", _fake_user(display_name="Follower")),
                "timestamp": overrides.pop("timestamp", _now()),
            },
            overrides,
        )

    @staticmethod
    def channel_raid(**overrides: Any) -> SimpleNamespace:
        viewer_count = overrides.pop("viewer_count", None)
        viewers = overrides.pop("viewers", None)
        if viewer_count is None and viewers is None:
            viewer_count = viewers = 42
        elif viewer_count is None:
            viewer_count = viewers
        elif viewers is None:
            viewers = viewer_count
        return _build_payload(
            {
                "from_broadcaster": overrides.pop("from_broadcaster", _fake_broadcaster("RaidLeader")),
                "viewer_count": viewer_count,
            },
            overrides,
        )

    @staticmethod
    def channel_subscription_gift(**overrides: Any) -> SimpleNamespace:
        return _build_payload(
            {
                "user": overrides.pop("user", _fake_user(display_name="Gifter")),
                "total": overrides.pop("total", 3),
                "cumulative_total": overrides.pop("cumulative_total", 20),
                "anonymous": overrides.pop("anonymous", False),
                "tier": overrides.pop("tier", "1000"),
            },
            overrides,
        )

    @staticmethod
    def channel_points_redemption(**overrides: Any) -> SimpleNamespace:
        reward = overrides.pop("reward", _fake_custom_reward())
        user_input_default = None
        if getattr(reward, "is_user_input_required", False):
            user_input_default = "Custom reward input"
        if user_input_default is None:
            user_input_default = "How many licks does it take to get to the center of a Tootsie Pop?"
        return _build_payload(
            {
                "id": overrides.pop("id", f"redemption_{randint(1000,9999)}"),
                "user": overrides.pop("user", _fake_user(display_name="RewardFan")),
                "reward": reward,
                "timestamp": overrides.pop("timestamp", _now()),
                "redeemed_at": overrides.pop("redeemed_at", _now()),
                "user_input": overrides.pop("user_input", user_input_default),
                "broadcaster": overrides.pop("broadcaster", _fake_broadcaster()),
                "status": overrides.pop("status", "FULFILLED"),
            },
            overrides,
        )

    @staticmethod
    def channel_points_auto_redeem(**overrides: Any) -> SimpleNamespace:
        reward = overrides.pop("reward", _fake_default_reward())
        user_input_default = None
        if getattr(reward, "is_user_input_required", False):
            user_input_default = "Auto reward input"
        if user_input_default is None:
            user_input_default = "Auto viewer input placeholder"
        return _build_payload(
            {
                "id": overrides.pop("id", f"auto_redeem_{randint(1000,9999)}"),
                "user": overrides.pop("user", _fake_user(display_name="DefaultRewardFan")),
                "reward": reward,
                "timestamp": overrides.pop("timestamp", _now()),
                "redeemed_at": overrides.pop("redeemed_at", _now()),
                "user_input": overrides.pop("user_input", user_input_default),
                "broadcaster": overrides.pop("broadcaster", _fake_broadcaster()),
                "status": overrides.pop("status", "FULFILLED"),
            },
            overrides,
        )

    @staticmethod
    def suspicious_user_message(**overrides: Any) -> SimpleNamespace:
        return _build_payload(
            {
                "user": overrides.pop("user", _fake_user(display_name="SuspiciousUser")),
                "message": overrides.pop("message", _ns(text="Check out this suspicious link")),
            },
            overrides,
        )

    @staticmethod
    def shared_chat_event(**overrides: Any) -> SimpleNamespace:
        return _build_payload(
            {
                "session_id": overrides.pop("session_id", f"session_{randint(1000,9999)}"),
                "timestamp": overrides.pop("timestamp", _now()),
            },
            overrides,
        )

    @staticmethod
    def broadcaster_event(**overrides: Any) -> SimpleNamespace:
        return _build_payload(
            {
                "broadcaster": overrides.pop("broadcaster", _fake_broadcaster()),
                "timestamp": overrides.pop("timestamp", _now()),
            },
            overrides,
        )

    @staticmethod
    def channel_poll(**overrides: Any) -> SimpleNamespace:
        return PayloadFactory.broadcaster_event(**overrides)

    @staticmethod
    def channel_prediction(**overrides: Any) -> SimpleNamespace:
        return PayloadFactory.broadcaster_event(**overrides)

    @staticmethod
    def light_shield_event(**overrides: Any) -> SimpleNamespace:
        return PayloadFactory.broadcaster_event(**overrides)

    @staticmethod
    def shoutout_event(**overrides: Any) -> SimpleNamespace:
        defaults = PayloadFactory.broadcaster_event(**overrides).__dict__
        defaults.setdefault("to_broadcaster", _fake_broadcaster("FriendStream"))
        return _build_payload(defaults, overrides)

    @staticmethod
    def automod_hold(**overrides: Any) -> SimpleNamespace:
        return _build_payload(
            {
                "user": overrides.pop("user", _fake_user(display_name="HeldUser")),
                "text": overrides.pop("text", "Message caught by AutoMod"),
                "level": overrides.pop("level", 3),
                "reason": overrides.pop("reason", "sexual"),
            },
            overrides,
        )

    @staticmethod
    def ad_break(**overrides: Any) -> SimpleNamespace:
        defaults = PayloadFactory.broadcaster_event(**overrides).__dict__
        defaults.setdefault("duration_seconds", overrides.pop("duration_seconds", 30))
        return _build_payload(defaults, overrides)


async def _invoke_listener(
    method_name: str,
    payload_factory: Callable[..., SimpleNamespace],
    **overrides: Any,
) -> SimpleNamespace:
    handler = _require_handler()
    payload = payload_factory(**overrides)
    listener = getattr(handler, method_name)
    await listener(payload)
    debug_print("Testing", f"Executed {method_name} with fake payload {payload}")
    return payload


# Chat message / cheer / subs -------------------------------------------------

async def test_chat_message(**overrides: Any) -> SimpleNamespace:
    return await _invoke_listener("event_message", PayloadFactory.chat_message, **overrides)

async def test_channel_cheer(**overrides: Any) -> SimpleNamespace:
    return await _invoke_listener("event_cheer", PayloadFactory.channel_cheer, **overrides)

async def test_channel_subscribe(**overrides: Any) -> SimpleNamespace:
    return await _invoke_listener("event_subscription", PayloadFactory.channel_subscribe, **overrides)

async def test_channel_subscribe_message(**overrides: Any) -> SimpleNamespace:
    return await _invoke_listener(
        "event_subscription_message", PayloadFactory.channel_subscribe_message, **overrides
    )

async def test_channel_subscription_end(**overrides: Any) -> SimpleNamespace:
    return await _invoke_listener(
        "event_subscription_end", PayloadFactory.channel_subscription_end, **overrides
    )

async def test_channel_follow(**overrides: Any) -> SimpleNamespace:
    return await _invoke_listener("event_follow", PayloadFactory.channel_follow, **overrides)


async def test_channel_raid(**overrides: Any) -> SimpleNamespace:
    return await _invoke_listener("event_raid", PayloadFactory.channel_raid, **overrides)

async def test_channel_subscription_gift(**overrides: Any) -> SimpleNamespace:
    return await _invoke_listener(
        "event_subscription_gift", PayloadFactory.channel_subscription_gift, **overrides
    )

async def test_gift_subscription_bundle(**overrides: Any) -> None:
    """Simulate a bulk gift: one gift payload plus three gifted subs."""
    gift_overrides = overrides.pop("gift_overrides", {}) or {}
    recipient_specs = overrides.pop("recipients", None)
    subscribe_overrides = overrides.pop("subscribe_overrides", {}) or {}

    await _invoke_listener(
        "event_subscription_gift",
        PayloadFactory.channel_subscription_gift,
        **gift_overrides,
    )

    default_recipients = [
        {"login": "giftedview1", "display_name": "GiftedViewOne"},
        {"login": "giftedview2", "display_name": "GiftedViewTwo"},
        {"login": "giftedview3", "display_name": "GiftedViewThree"},
    ]
    targets = recipient_specs or default_recipients
    for spec in targets[:3]:
        user = _fake_user(display_name=spec.get("display_name", "GiftedViewer"), login=spec.get("login"))
        payload_kwargs = {**subscribe_overrides, "user": user, "gift": True}
        await _invoke_listener(
            "event_subscription",
            PayloadFactory.channel_subscribe,
            **payload_kwargs,
        )


# Channel points --------------------------------------------------------------

async def test_channel_points_redeem(**overrides: Any) -> SimpleNamespace:
    return await _invoke_listener(
        "event_custom_redemption_add", PayloadFactory.channel_points_redemption, **overrides
    )


async def test_channel_points_auto_redeem(**overrides: Any) -> SimpleNamespace:
    return await _invoke_listener(
        "event_automatic_redemption_add", PayloadFactory.channel_points_auto_redeem, **overrides
    )


async def test_suspicious_user_message(**overrides: Any) -> SimpleNamespace:
    return await _invoke_listener(
        "event_suspicious_user_message", PayloadFactory.suspicious_user_message, **overrides
    )


# Shared chat -----------------------------------------------------------------

async def test_shared_chat_session_begin(**overrides: Any) -> SimpleNamespace:
    return await _invoke_listener(
        "event_shared_chat_begin", PayloadFactory.shared_chat_event, **overrides
    )


async def test_shared_chat_session_update(**overrides: Any) -> SimpleNamespace:
    return await _invoke_listener(
        "event_shared_chat_update", PayloadFactory.shared_chat_event, **overrides
    )


async def test_shared_chat_session_end(**overrides: Any) -> SimpleNamespace:
    return await _invoke_listener(
        "event_shared_chat_end", PayloadFactory.shared_chat_event, **overrides
    )


# Stream status ---------------------------------------------------------------

async def test_stream_online(**overrides: Any) -> SimpleNamespace:
    return await _invoke_listener("event_stream_online", PayloadFactory.broadcaster_event, **overrides)


async def test_stream_offline(**overrides: Any) -> SimpleNamespace:
    return await _invoke_listener("event_stream_offline", PayloadFactory.broadcaster_event, **overrides)


# Charity events --------------------------------------------------------------

async def test_charity_campaign_start(**overrides: Any) -> SimpleNamespace:
    return await _invoke_listener(
        "event_charity_campaign_start", PayloadFactory.broadcaster_event, **overrides
    )


async def test_charity_campaign_progress(**overrides: Any) -> SimpleNamespace:
    return await _invoke_listener(
        "event_charity_campaign_progress", PayloadFactory.broadcaster_event, **overrides
    )


async def test_charity_campaign_stop(**overrides: Any) -> SimpleNamespace:
    return await _invoke_listener(
        "event_charity_campaign_stop", PayloadFactory.broadcaster_event, **overrides
    )


# Goals -----------------------------------------------------------------------

async def test_goal_begin(**overrides: Any) -> SimpleNamespace:
    return await _invoke_listener("event_goal_begin", PayloadFactory.broadcaster_event, **overrides)


async def test_goal_progress(**overrides: Any) -> SimpleNamespace:
    return await _invoke_listener("event_goal_progress", PayloadFactory.broadcaster_event, **overrides)


async def test_goal_end(**overrides: Any) -> SimpleNamespace:
    return await _invoke_listener("event_goal_end", PayloadFactory.broadcaster_event, **overrides)


# Hype train ------------------------------------------------------------------

async def test_hype_train_begin(**overrides: Any) -> SimpleNamespace:
    return await _invoke_listener("event_hype_train", PayloadFactory.broadcaster_event, **overrides)


async def test_hype_train_progress(**overrides: Any) -> SimpleNamespace:
    return await _invoke_listener(
        "event_hype_train_progress", PayloadFactory.broadcaster_event, **overrides
    )


async def test_hype_train_end(**overrides: Any) -> SimpleNamespace:
    return await _invoke_listener("event_hype_train_end", PayloadFactory.broadcaster_event, **overrides)


# Polls -----------------------------------------------------------------------

async def test_channel_poll_begin(**overrides: Any) -> SimpleNamespace:
    return await _invoke_listener("event_poll_begin", PayloadFactory.channel_poll, **overrides)


async def test_channel_poll_progress(**overrides: Any) -> SimpleNamespace:
    return await _invoke_listener(
        "event_poll_progress", PayloadFactory.channel_poll, **overrides
    )


async def test_channel_poll_end(**overrides: Any) -> SimpleNamespace:
    return await _invoke_listener("event_poll_end", PayloadFactory.channel_poll, **overrides)


# Predictions -----------------------------------------------------------------

async def test_channel_prediction_begin(**overrides: Any) -> SimpleNamespace:
    return await _invoke_listener(
        "event_prediction_begin", PayloadFactory.channel_prediction, **overrides
    )


async def test_channel_prediction_progress(**overrides: Any) -> SimpleNamespace:
    return await _invoke_listener(
        "event_prediction_progress", PayloadFactory.channel_prediction, **overrides
    )


async def test_channel_prediction_lock(**overrides: Any) -> SimpleNamespace:
    return await _invoke_listener(
        "event_prediction_lock", PayloadFactory.channel_prediction, **overrides
    )


async def test_channel_prediction_end(**overrides: Any) -> SimpleNamespace:
    return await _invoke_listener(
        "event_prediction_end", PayloadFactory.channel_prediction, **overrides
    )


# Shield mode -----------------------------------------------------------------

async def test_shield_mode_begin(**overrides: Any) -> SimpleNamespace:
    return await _invoke_listener(
        "event_shield_mode_begin", PayloadFactory.light_shield_event, **overrides
    )


async def test_shield_mode_end(**overrides: Any) -> SimpleNamespace:
    return await _invoke_listener(
        "event_shield_mode_end", PayloadFactory.light_shield_event, **overrides
    )


# Shoutouts -------------------------------------------------------------------

async def test_shoutout_create(**overrides: Any) -> SimpleNamespace:
    return await _invoke_listener("event_shoutout_create", PayloadFactory.shoutout_event, **overrides)


async def test_shoutout_receive(**overrides: Any) -> SimpleNamespace:
    return await _invoke_listener("event_shoutout_receive", PayloadFactory.shoutout_event, **overrides)


# AutoMod & ads ----------------------------------------------------------------

async def test_automod_message_hold(**overrides: Any) -> SimpleNamespace:
    return await _invoke_listener(
        "event_automod_message_hold", PayloadFactory.automod_hold, **overrides
    )


async def test_ad_break_begin(**overrides: Any) -> SimpleNamespace:
    return await _invoke_listener("event_ad_break", PayloadFactory.ad_break, **overrides)
