import pytest
from contract import Case
from contract_invariants import INVARIANT_CASES
from contract_queue import QUEUE_CASES
from contract_queue_fencing import FENCING_CASES
from contract_stores import STORE_CASES
from contract_upsert import UPSERT_CASES

from feedback_ingest.api.deps import Adapters

CASES = STORE_CASES + UPSERT_CASES + QUEUE_CASES + FENCING_CASES + INVARIANT_CASES


@pytest.mark.parametrize("case", CASES, ids=lambda case: case.__name__)
def test_contract(case: Case, adapters: Adapters) -> None:
    case(adapters)
