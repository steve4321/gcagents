from __future__ import annotations

from copy import deepcopy

CHARACTER_SPRITE_WORKFLOW: dict = {
    "1": {
        "class_type": "CheckpointLoaderSimple",
        "inputs": {"ckpt_name": "v1-5-pruned-emaonly.safetensors"},
    },
    "2": {
        "class_type": "CLIPTextEncode",
        "inputs": {"text": "", "clip": ["1", 1]},
    },
    "3": {
        "class_type": "CLIPTextEncode",
        "inputs": {"text": "", "clip": ["1", 1]},
    },
    "4": {
        "class_type": "EmptyLatentImage",
        "inputs": {"width": 512, "height": 512, "batch_size": 1},
    },
    "5": {
        "class_type": "KSampler",
        "inputs": {
            "seed": 42,
            "steps": 20,
            "cfg": 7,
            "sampler_name": "euler",
            "scheduler": "normal",
            "denoise": 1,
            "model": ["1", 0],
            "positive": ["2", 0],
            "negative": ["3", 0],
            "latent_image": ["4", 0],
        },
    },
    "6": {
        "class_type": "VAEDecode",
        "inputs": {"samples": ["5", 0], "vae": ["1", 2]},
    },
    "7": {
        "class_type": "SaveImage",
        "inputs": {"filename_prefix": "character", "images": ["6", 0]},
    },
}

BACKGROUND_WORKFLOW: dict = {
    "1": {
        "class_type": "CheckpointLoaderSimple",
        "inputs": {"ckpt_name": "v1-5-pruned-emaonly.safetensors"},
    },
    "2": {
        "class_type": "CLIPTextEncode",
        "inputs": {"text": "", "clip": ["1", 1]},
    },
    "3": {
        "class_type": "CLIPTextEncode",
        "inputs": {"text": "", "clip": ["1", 1]},
    },
    "4": {
        "class_type": "EmptyLatentImage",
        "inputs": {"width": 1024, "height": 512, "batch_size": 1},
    },
    "5": {
        "class_type": "KSampler",
        "inputs": {
            "seed": 42,
            "steps": 20,
            "cfg": 7,
            "sampler_name": "euler",
            "scheduler": "normal",
            "denoise": 1,
            "model": ["1", 0],
            "positive": ["2", 0],
            "negative": ["3", 0],
            "latent_image": ["4", 0],
        },
    },
    "6": {
        "class_type": "VAEDecode",
        "inputs": {"samples": ["5", 0], "vae": ["1", 2]},
    },
    "7": {
        "class_type": "SaveImage",
        "inputs": {"filename_prefix": "background", "images": ["6", 0]},
    },
}

UI_ELEMENT_WORKFLOW: dict = {
    "1": {
        "class_type": "CheckpointLoaderSimple",
        "inputs": {"ckpt_name": "v1-5-pruned-emaonly.safetensors"},
    },
    "2": {
        "class_type": "CLIPTextEncode",
        "inputs": {"text": "", "clip": ["1", 1]},
    },
    "3": {
        "class_type": "CLIPTextEncode",
        "inputs": {"text": "", "clip": ["1", 1]},
    },
    "4": {
        "class_type": "EmptyLatentImage",
        "inputs": {"width": 256, "height": 256, "batch_size": 1},
    },
    "5": {
        "class_type": "KSampler",
        "inputs": {
            "seed": 42,
            "steps": 20,
            "cfg": 7,
            "sampler_name": "euler",
            "scheduler": "normal",
            "denoise": 1,
            "model": ["1", 0],
            "positive": ["2", 0],
            "negative": ["3", 0],
            "latent_image": ["4", 0],
        },
    },
    "6": {
        "class_type": "VAEDecode",
        "inputs": {"samples": ["5", 0], "vae": ["1", 2]},
    },
    "7": {
        "class_type": "SaveImage",
        "inputs": {"filename_prefix": "ui_element", "images": ["6", 0]},
    },
}


def build_workflow(template: dict, positive_prompt: str, negative_prompt: str, seed: int = 42) -> dict:
    wf = deepcopy(template)
    wf["2"]["inputs"]["text"] = positive_prompt
    wf["3"]["inputs"]["text"] = negative_prompt
    wf["5"]["inputs"]["seed"] = seed
    return wf
