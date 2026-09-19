from comfycluster_agent.gpu import discover_gpus


def test_mock_gpu_discovery():
    gpus = discover_gpus(2)
    assert len(gpus) == 2
    assert gpus[0].index == 0
    assert gpus[1].memory_total_mb == 32768
