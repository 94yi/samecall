"""The packaged adapter keeps the original caller-facing method."""
from binding import PLAN
from call_plan import adapted
from service import DeskV3

ParcelDesk = adapted(DeskV3, PLAN)
