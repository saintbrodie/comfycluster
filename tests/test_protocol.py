from comfycluster_common.models import GPUInfo, HostRegistration
from comfycluster_common.protocol import parse_agent_message


def test_registration_round_trip():
    message = HostRegistration(
        host_id="render-01",
        hostname="render-01",
        os_name="Windows",
        os_version="11",
        agent_version="0.1.0",
        gpus=[GPUInfo(index=0, uuid="GPU-1", name="RTX", memory_total_mb=32768)],
    )
    parsed = parse_agent_message(message.model_dump_json())
    assert isinstance(parsed, HostRegistration)
    assert parsed.gpus[0].uuid == "GPU-1"
