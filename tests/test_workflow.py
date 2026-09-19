from comfycluster_controller.workflow import analyze_workflow


def test_workflow_analysis_extracts_nodes_and_model_like_inputs_only():
    workflow = {
        "1": {
            "class_type": "CheckpointLoaderSimple",
            "inputs": {
                "ckpt_name": "flux/flux1-dev.safetensors",
                "prompt": "a sentence mentioning model but not a filename",
            },
        },
        "2": {
            "class_type": "LoraLoader",
            "inputs": {
                "lora_name": "style.safetensors",
                "nested": ["not-a-model", {"vae": "vae/model.vae.pt"}],
            },
        },
    }
    result = analyze_workflow(workflow)
    assert result.node_types == frozenset({"CheckpointLoaderSimple", "LoraLoader"})
    assert result.model_refs == frozenset(
        {"flux/flux1-dev.safetensors", "style.safetensors", "vae/model.vae.pt"}
    )
