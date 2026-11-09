"""Work around a clock problem in the BehaviorGPT SDK.

The SDK stamps a history's events about one second before *this computer's*
"now", and the API ignores events that are later than *its* clock. When the
computer's clock runs a few seconds fast (this one was ~5 s ahead), every
viewed item looks like it is in the future and is silently dropped: rankings
then ignore the history entirely (searches still work, which hides it).

Importing this module shifts the SDK's clock back by SKEW. Reported as a
question for the Unbox AI team in README.md.
"""

from datetime import datetime, timedelta

from behaviorgpt import _client

SKEW = timedelta(seconds=60)


class _ShiftedDatetime(datetime):
    @classmethod
    def now(cls, tz=None):
        return datetime.now(tz) - SKEW


_client.datetime = _ShiftedDatetime
