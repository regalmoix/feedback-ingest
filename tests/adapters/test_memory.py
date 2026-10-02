import pytest
from contract import Adapters, Case
from contract_queue import QUEUE_CASES
from contract_queue_fencing import FENCING_CASES
from contract_stores import STORE_CASES
from contract_upsert import UPSERT_CASES

from feedback_ingest.adapters.memory.clock import FixedClock
from feedback_ingest.adapters.memory.queue import MemoryRawEventQueue
from feedback_ingest.adapters.memory.stores import (
    MemoryFeedbackStore,
    MemorySourceStore,
    MemoryTenantStore,
)

CASES = STORE_CASES + UPSERT_CASES + QUEUE_CASES + FENCING_CASES


@pytest.mark.parametrize("case", CASES, ids=lambda case: case.__name__)
def test_contract(case: Case, clock: FixedClock) -> None:
    case(
        Adapters(
            MemoryTenantStore(),
            MemorySourceStore(),
            MemoryFeedbackStore(),
            MemoryRawEventQueue(),
            clock,
        )
    )
