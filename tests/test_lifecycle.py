from __future__ import annotations

import pytest

from mosaic_harness import HarnessEvent, InMemoryRunJournal, MosaicHarness


class CloseableJournal(InMemoryRunJournal):
    def __init__(self) -> None:
        super().__init__()
        self.closed = False

    def close(self) -> None:
        self.closed = True


def test_harness_close_releases_closeable_journal() -> None:
    journal = CloseableJournal()
    sdk = MosaicHarness(journal=journal)
    journal.append(HarnessEvent("run.started", "agent", "thread", "run"))

    sdk.close()

    assert journal.closed is True


def test_harness_context_manager_closes_journal() -> None:
    journal = CloseableJournal()

    with MosaicHarness(journal=journal):
        pass

    assert journal.closed is True


@pytest.mark.asyncio
async def test_harness_async_context_manager_closes_journal() -> None:
    journal = CloseableJournal()

    async with MosaicHarness(journal=journal):
        pass

    assert journal.closed is True
