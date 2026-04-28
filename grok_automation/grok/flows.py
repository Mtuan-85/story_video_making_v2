"""Declarative flow definitions.

Each flow is a list of step dicts. The runner resolves params:
  from_prompt: <key>      → state["current_prompt"][key]
  from_config: <key>      → config[key]
  from_var: <name>        → state["vars"][name] (supports "foo.bar" dotted access)
  masonry_from_var: <key> → resolved like from_var, used by click_image
  value: <literal>        → use as-is

Flag `loop_per_prompt: True` means runner repeats the steps for each prompt.

UI auto-selects flow:
  type=image, no refs → text_to_image
  type=image, has ref → image_to_image
  type=video, no refs → text_to_video
  type=video, has ref → image_to_video
"""

FLOWS = {
    "text_to_image": {
        "name": "Text-to-Image",
        "loop_per_prompt": True,
        "steps": [
            {"action": "ensure_at", "url": "/imagine"},
            {"action": "set_mode", "value": "image"},
            {"action": "set_quality", "from_config": "quality"},
            {"action": "set_aspect", "from_config": "aspect"},
            {"action": "verify_input_empty"},
            {"action": "fill_prompt", "from_prompt": "text"},
            {"action": "human_pause", "min_ms": 500, "max_ms": 1200},
            {"action": "submit_and_wait_ready",
             "target_count_from_config": "target_count",
             "save_to": "ready_result"},
            {"action": "save_candidates_log",
             "target_count_from_config": "target_count"},
            {"action": "pick_image", "save_to": "best_idx"},
            {"action": "click_image",
             "from_var": "best_idx",
             "masonry_from_var": "ready_result.masonry_index"},
            {"action": "wait_url_match", "pattern": r".*/imagine/post/"},
            {"action": "human_pause", "min_ms": 600, "max_ms": 1200},
            {"action": "download", "prefix": "pic"},
            {"action": "human_pause", "min_ms": 500, "max_ms": 1000},
            {"action": "click_back"},
            {"action": "wait_url_match", "pattern": r".*/imagine(?!/post)"},
        ],
    },

    "image_to_image": {
        "name": "Image-to-Image",
        "loop_per_prompt": True,
        "steps": [
            {"action": "ensure_at", "url": "/imagine"},
            {"action": "set_mode", "value": "image"},
            {"action": "set_quality", "from_config": "quality"},
            {"action": "set_aspect", "from_config": "aspect"},
            {"action": "upload_ref_if_present", "from_prompt": "ref"},
            {"action": "fill_prompt", "from_prompt": "text"},
            {"action": "human_pause", "min_ms": 500, "max_ms": 1200},
            {"action": "submit_and_wait_ready",
             "target_count_from_config": "target_count",
             "save_to": "ready_result"},
            {"action": "save_candidates_log",
             "target_count_from_config": "target_count"},
            {"action": "pick_image", "save_to": "best_idx"},
            {"action": "click_image",
             "from_var": "best_idx",
             "masonry_from_var": "ready_result.masonry_index"},
            {"action": "wait_url_match", "pattern": r".*/imagine/post/"},
            {"action": "human_pause", "min_ms": 600, "max_ms": 1200},
            {"action": "download", "prefix": "pic"},
            {"action": "human_pause", "min_ms": 500, "max_ms": 1000},
            {"action": "click_back"},
            {"action": "wait_url_match", "pattern": r".*/imagine(?!/post)"},
        ],
    },

    "text_to_video": {
        "name": "Text-to-Video",
        "loop_per_prompt": True,
        "steps": [
            {"action": "ensure_at", "url": "/imagine"},
            {"action": "set_mode", "value": "video"},
            {"action": "set_video_resolution", "from_config": "resolution"},
            {"action": "set_video_duration", "from_config": "duration"},
            {"action": "set_aspect", "from_config": "aspect"},
            {"action": "fill_prompt", "from_prompt": "text"},
            {"action": "human_pause", "min_ms": 500, "max_ms": 1200},
            {"action": "click_submit"},
            {"action": "wait_url_match", "pattern": r".*/imagine/post/"},
            {"action": "wait_video_ready"},
            {"action": "human_pause", "min_ms": 600, "max_ms": 1200},
            {"action": "download", "prefix": "vid"},
            {"action": "human_pause", "min_ms": 500, "max_ms": 1000},
            {"action": "click_back"},
            {"action": "wait_url_match", "pattern": r".*/imagine(?!/post)"},
        ],
    },

    "image_to_video": {
        "name": "Image-to-Video",
        "loop_per_prompt": True,
        "steps": [
            {"action": "ensure_at", "url": "/imagine"},
            {"action": "set_mode", "value": "video"},
            {"action": "set_video_resolution", "from_config": "resolution"},
            {"action": "set_video_duration", "from_config": "duration"},
            {"action": "set_aspect", "from_config": "aspect"},
            {"action": "upload_ref_if_present", "from_prompt": "ref"},
            {"action": "fill_prompt", "from_prompt": "text"},
            {"action": "human_pause", "min_ms": 500, "max_ms": 1200},
            {"action": "click_submit"},
            {"action": "wait_url_match", "pattern": r".*/imagine/post/"},
            {"action": "wait_video_ready"},
            {"action": "human_pause", "min_ms": 600, "max_ms": 1200},
            {"action": "download", "prefix": "vid"},
            {"action": "human_pause", "min_ms": 500, "max_ms": 1000},
            {"action": "click_back"},
            {"action": "wait_url_match", "pattern": r".*/imagine(?!/post)"},
        ],
    },
}
