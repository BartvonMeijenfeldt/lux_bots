import logging
import time
from dataclasses import dataclass

from config import CONFIG

logger = logging.getLogger(__name__)


@dataclass
class TimeTracker:
    """Tracks time used on current move to figure out if we need to abort scheduling early to not go over time."""

    start_time: float
    DEBUG_MODE: bool

    def _get_time_taken(self) -> float:
        return time.time() - self.start_time

    def is_out_of_time_main_scheduling(self) -> bool:
        if self.DEBUG_MODE:
            return False

        is_out_of_time = self._get_time_taken() > CONFIG.OUT_OF_TIME_MAIN_SCHEDULING

        if is_out_of_time:
            logger.critical("RAN OUT OF TIME MAIN SCHEDULING")

        return is_out_of_time

    def is_out_of_time_scheduling_unassigned_units(self) -> bool:
        if self.DEBUG_MODE:
            return False

        is_out_of_time = self._get_time_taken() > CONFIG.OUT_OF_TIME_UNASSIGNED_SCHEDULING

        if is_out_of_time:
            logger.critical("RAN OUT OF TIME UNASSIGNED SCHEDULING")

        return is_out_of_time
