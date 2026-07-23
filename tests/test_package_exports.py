"""Compatibility checks for documented package-level imports."""

from feelies.bus import EventBus
from feelies.core import (
    Clock,
    ConfigSnapshot,
    Configuration,
    EventSerializer,
    IllegalTransition,
    SequenceGenerator,
    SimulatedClock,
    StateMachine,
    TransitionRecord,
    WallClock,
    make_correlation_id,
)
from feelies.kernel import (
    MacroState,
    MicroState,
    create_macro_state_machine,
    create_micro_state_machine,
)


def test_package_level_exports_remain_importable() -> None:
    exports = (
        EventBus,
        Clock,
        ConfigSnapshot,
        Configuration,
        EventSerializer,
        IllegalTransition,
        SequenceGenerator,
        SimulatedClock,
        StateMachine,
        TransitionRecord,
        WallClock,
        make_correlation_id,
        MacroState,
        MicroState,
        create_macro_state_machine,
        create_micro_state_machine,
    )

    assert all(export is not None for export in exports)
