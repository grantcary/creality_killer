from creality_killer.core.queue import PrintQueue


def test_queue_flow():
    q = PrintQueue()
    for n in "abc":
        q.add(n)
    q.add("a")
    q.move(3, 0)
    assert q.items == ["a", "a", "b", "c"]
    assert not q.job_started("b")
    assert q.job_started("a") and q.items == ["a", "b", "c"]
    q.remove_at(1)
    assert q.items == ["a", "c"]
