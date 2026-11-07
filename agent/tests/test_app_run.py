import threading

from chat2cart.app import PART_DIED_EXIT_CODE, Service, run_until_stopped


class FakePart:
    def __init__(self, alive: bool = True) -> None:
        self.alive = alive
        self.stopped = False

    def is_alive(self) -> bool:
        return self.alive

    def stop(self) -> None:
        self.stopped = True


def test_stops_every_part_and_exits_zero_when_asked_to_stop() -> None:
    part = FakePart()
    stop = threading.Event()
    stop.set()

    code = run_until_stopped(Service([part]), stop)

    assert (code, part.stopped) == (0, True)


def test_exits_non_zero_so_the_supervisor_restarts_when_a_part_dies() -> None:
    healthy, dead = FakePart(), FakePart(alive=False)

    code = run_until_stopped(Service([healthy, dead]), threading.Event(), 0.01)

    assert code == PART_DIED_EXIT_CODE
    assert healthy.stopped
