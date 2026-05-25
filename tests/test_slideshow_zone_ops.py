from ui.dialogs.slideshow_zone_ops import (
    add_default_zone,
    apply_sound_to_all,
    delete_zone,
    move_zone,
    resequence_zones,
)


def _zones():
    return [
        {"zone_id": 1, "label": "one", "polygon": [[0, 0], [10, 0], [10, 10]], "order": 1},
        {"zone_id": 2, "label": "two", "polygon": [[20, 0], [30, 0], [30, 10]], "order": 2},
        {"zone_id": 3, "label": "three", "polygon": [[40, 0], [50, 0], [50, 10]], "order": 3},
    ]


def test_move_zone_reorders_and_resequences():
    zones = _zones()

    assert move_zone(zones, 3, -1) is True

    assert [z["zone_id"] for z in zones] == [1, 3, 2]
    assert [z["order"] for z in zones] == [1, 2, 3]


def test_delete_zone_removes_and_resequences():
    zones = _zones()

    removed = delete_zone(zones, 2)

    assert removed["label"] == "two"
    assert [z["zone_id"] for z in zones] == [1, 3]
    assert [z["order"] for z in zones] == [1, 2]


def test_add_default_zone_uses_next_id_and_center_polygon():
    zones = _zones()

    zone = add_default_zone(zones, image_size=(100, 80))

    assert zone["zone_id"] == 4
    assert zone["label"] == "zone_4"
    assert zone["order"] == 4
    assert zone["polygon"] == [[35, 25], [65, 25], [65, 55], [35, 55]]
    assert zones[-1] is zone


def test_resequence_zones_assigns_order_field():
    zones = [{"zone_id": 9}, {"zone_id": 4}]

    resequence_zones(zones)

    assert [z["order"] for z in zones] == [1, 2]


def test_apply_sound_to_all_updates_every_zone():
    zones = _zones()

    changed = apply_sound_to_all(zones, "whoosh")

    assert changed == 3
    assert [z["sound"] for z in zones] == ["whoosh", "whoosh", "whoosh"]
