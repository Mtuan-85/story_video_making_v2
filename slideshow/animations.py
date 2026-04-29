"""
Animation library cho ffmpeg overlay.

Mỗi animation trả về (x_expression, y_expression) cho overlay filter.
- target_x, target_y: vị trí cuối của object (đã tính trong canvas coords)
- start: thời điểm animation bắt đầu (s)
- dur: thời lượng animation (s)
- canvas_w, canvas_h: kích thước canvas output

Trong overlay expression:
- W, H = main video dimensions (canvas)
- w, h = overlay dimensions (object đã scaled)
- t = current time
"""

ANIMATION_DURATION = 0.5
SUPPORTED_ANIMATIONS = [
    "fade_pop", "slide_left", "slide_right",
    "slide_top", "slide_bottom", "zoom_in"
]


def build_animation_exprs(animation_type, start, target_x, target_y,
                          canvas_w, canvas_h, dur=ANIMATION_DURATION):
    """Trả về (x_expr, y_expr) cho overlay filter."""
    end = start + dur

    if animation_type == "slide_left":
        x_expr = (
            f"if(lt(t,{start}),-w,"
            f"if(lt(t,{end}),-w+((t-{start})/{dur})*({target_x}+w),{target_x}))"
        )
        y_expr = str(target_y)

    elif animation_type == "slide_right":
        x_expr = (
            f"if(lt(t,{start}),{canvas_w},"
            f"if(lt(t,{end}),{canvas_w}-((t-{start})/{dur})*({canvas_w}-{target_x}),{target_x}))"
        )
        y_expr = str(target_y)

    elif animation_type == "slide_top":
        x_expr = str(target_x)
        y_expr = (
            f"if(lt(t,{start}),-h,"
            f"if(lt(t,{end}),-h+((t-{start})/{dur})*({target_y}+h),{target_y}))"
        )

    elif animation_type == "slide_bottom":
        x_expr = str(target_x)
        y_expr = (
            f"if(lt(t,{start}),{canvas_h},"
            f"if(lt(t,{end}),{canvas_h}-((t-{start})/{dur})*({canvas_h}-{target_y}),{target_y}))"
        )

    else:
        x_expr = str(target_x)
        y_expr = str(target_y)

    return x_expr, y_expr


def needs_scale_animation(animation_type):
    return animation_type in ("zoom_in", "fade_pop")


def build_scale_animation_filter(animation_type, start, target_w, target_h,
                                 dur=ANIMATION_DURATION):
    """scale filter cho zoom_in / fade_pop."""
    end = start + dur

    if animation_type == "zoom_in":
        w_expr = (
            f"if(lt(t,{start}),{target_w}*0.5,"
            f"if(lt(t,{end}),{target_w}*(0.5+0.5*(t-{start})/{dur}),{target_w}))"
        )
        h_expr = (
            f"if(lt(t,{start}),{target_h}*0.5,"
            f"if(lt(t,{end}),{target_h}*(0.5+0.5*(t-{start})/{dur}),{target_h}))"
        )
        return f"scale=w='{w_expr}':h='{h_expr}':eval=frame"

    elif animation_type == "fade_pop":
        w_expr = (
            f"if(lt(t,{start}),{target_w}*0.85,"
            f"if(lt(t,{end}),{target_w}*(0.85+0.15*(t-{start})/{dur}),{target_w}))"
        )
        h_expr = (
            f"if(lt(t,{start}),{target_h}*0.85,"
            f"if(lt(t,{end}),{target_h}*(0.85+0.15*(t-{start})/{dur}),{target_h}))"
        )
        return f"scale=w='{w_expr}':h='{h_expr}':eval=frame"

    return None
