"""The packaged adapter keeps the original caller-facing method."""
from binding import METHOD
from service import DeskV2


class ParcelDesk(DeskV2):
    def dispatch(self, lane, request, parcel):
        return getattr(self, METHOD)(lane, request, parcel)
