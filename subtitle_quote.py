#!/usr/bin/env python3
"""
聊天字幕视频生成器 subtitle_quote
每条独立渲染，微信风格配色/布局，带头像+名字+打字机气泡效果

用法：
  # 单条渲染（默认微信灰背景，h264/mp4）
  python3 subtitle_quote.py "国冰: AI时代，你准备好了吗？" -o quote.mp4

  # 批量渲染（从文件）
  python3 subtitle_quote.py input.txt -o output_dir/

  # 透明背景（需 DaVinci 等专业软件，VLC 不支持）
  python3 subtitle_quote.py "国冰: 你好" -o quote.mov --transparent

  # 指定头像
  python3 subtitle_quote.py "国冰: 你好" -o quote.mp4 --avatar avatar.jpg

输入格式（每行一条）：
  名字: 说话内容
  名字: 下一句话

样式：默认左侧（头像名在左，气泡在右），加 --right 切换右侧
"""

import argparse
import os
import re
import subprocess
from PIL import Image, ImageDraw, ImageFont

# ── 默认配置 ──────────────────────────────────────────────

FONT = "/home/robin/.local/share/fonts/NotoSansSC-Medium.ttf"
FONT_BOLD = "/home/robin/.local/share/fonts/NotoSansSC-SemiBold.ttf"
TEXT_SIZE = 48  # 气泡文字大小
NAME_SIZE = 32  # 名字大小
AVATAR_SIZE = 100  # 头像尺寸
BUBBLE_PAD = (40, 20, 40, 60)  # 气泡内边距 (l, t, r, b)
BUBBLE_RADIUS = 16  # 气泡圆角（微信风格：小圆角）
AVATAR_GAP = 48  # 头像到气泡间距
VERTICAL_OFFSET = 0  # 垂直偏移（正=上移）
LINE_GAP = 30  # 文本行间距
LETTER_SPACING = 3  # 字符间距（px）
MAX_WIDTH = 860  # 气泡最大宽度
FPS = 24
FRAMES_PER_CHAR = 2  # 每字符持续帧数（越大打字越慢）
FADE_SPAN = 5  # 淡入窗口（最近几个字符同时渐变）

# 颜色（暗色模式，统一 RGBA 四元组）
BUBBLE_COLOR_OTHER = (46, 46, 46, 255)  # 对方气泡：暗灰
BUBBLE_COLOR_SELF = (67, 107, 47, 255)  # 自己气泡：暗绿
TEXT_COLOR = (230, 230, 230, 255)  # 文字：浅白
NAME_COLOR = (153, 153, 153, 255)  # 名字：灰色
BG_COLOR = (17, 17, 17, 255)  # 默认背景：深黑
AVATAR_COLORS = [  # 头像底色
    (66, 133, 244, 255),
    (234, 67, 53, 255),
    (251, 188, 4, 255),
    (52, 168, 83, 255),
    (142, 68, 173, 255),
    (230, 126, 34, 255),
]

# ── 默认头像生成 ──────────────────────────────────────────


def make_avatar(text, size, color=None):
    """生成默认圆形头像（首字母 + 纯色背景）"""
    if color is None:
        idx = abs(hash(text)) % len(AVATAR_COLORS)
        color = AVATAR_COLORS[idx]
    img = Image.new("RGBA", (size, size), color)
    draw = ImageDraw.Draw(img)
    try:
        font = ImageFont.truetype(FONT, size // 2)
    except:
        font = ImageFont.load_default()
    ch = text.strip()[0] if text.strip() else "?"
    bbox = draw.textbbox((0, 0), ch, font=font)
    tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
    x = (size - tw) // 2 - bbox[0]
    y = (size - th) // 2 - bbox[1]
    draw.text((x, y), ch, fill="white", font=font)
    # 圆形遮罩
    mask = Image.new("L", (size, size), 0)
    ImageDraw.Draw(mask).ellipse((0, 0, size, size), fill=255)
    img.putalpha(mask)
    return img


def load_avatar(path, size):
    """加载图片并裁剪为圆形"""
    if not path or not os.path.exists(path):
        return None
    img = Image.open(path).convert("RGBA")
    img = img.resize((size, size), Image.LANCZOS)
    mask = Image.new("L", (size, size), 0)
    ImageDraw.Draw(mask).ellipse((0, 0, size, size), fill=255)
    img.putalpha(mask)
    return img


# ── 文字排版 ──────────────────────────────────────────────


def word_wrap(text, font, max_width, draw):
    """逐字换行（含字间距），返回行列表"""
    lines = []
    cur = ""
    for ch in text:
        test = cur + ch
        bbox = draw.textbbox((0, 0), test, font=font)
        w = bbox[2] - bbox[0] + LETTER_SPACING * max(len(test) - 1, 0)
        if w > max_width and cur:
            lines.append(cur)
            cur = ch
        else:
            cur = test
    if cur:
        lines.append(cur)
    return lines


def measure_block(lines, font, draw):
    """测量文本块尺寸（含字间距）"""
    max_w = max_h = 0
    for i, line in enumerate(lines):
        bbox = draw.textbbox((0, 0), line, font=font)
        w = bbox[2] - bbox[0] + LETTER_SPACING * max(len(line) - 1, 0)
        h = bbox[3] - bbox[1]
        max_w = max(max_w, w)
        max_h += h + (LINE_GAP if i < len(lines) - 1 else 0)
    return max_w, max_h


# ── 单帧渲染 ──────────────────────────────────────────────


def render_quote(
    name,
    visible_text,
    side,
    avatar_img,
    canvas_w=1920,
    canvas_h=1080,
    full_text=None,
    bg_color=None,
    alphas=None,
):
    """渲染一帧：头像 + 名字 + 气泡 + 打字机文字

    alphas: 逐字符不透明度列表 len=len(visible_text)，None 表示全部 1.0
    """
    if full_text is None:
        full_text = visible_text

    frame = Image.new("RGBA", (canvas_w, canvas_h), bg_color or (0, 0, 0, 0))
    draw = ImageDraw.Draw(frame)

    font = ImageFont.truetype(FONT, TEXT_SIZE)
    name_font = ImageFont.truetype(FONT, NAME_SIZE)

    # ── 用完整文本预计算气泡尺寸，保证头像位置固定 ──
    full_lines = word_wrap(full_text, font, MAX_WIDTH, draw)
    fw, fh = measure_block(full_lines, font, draw)
    bw = fw + BUBBLE_PAD[0] + BUBBLE_PAD[2]
    bh = fh + BUBBLE_PAD[1] + BUBBLE_PAD[3]
    bw = max(bw, 100)  # 最小宽度

    # ── 当前可见文本的排版 ──
    lines = word_wrap(visible_text, font, MAX_WIDTH, draw)

    # 名字尺寸
    bbox_n = draw.textbbox((0, 0), name, font=name_font)
    nw, nh = bbox_n[2] - bbox_n[0], bbox_n[3] - bbox_n[1]
    name_gap = 4  # 头像到名字的间距

    # 整体内容块：左列(头像+名字) + 间距 + 右列(气泡)，顶部对齐
    avatar_col_h = AVATAR_SIZE + name_gap + nh
    content_w = AVATAR_SIZE + AVATAR_GAP + bw
    content_h = max(avatar_col_h, bh)

    # 居中定位（整体内容块）
    base_x = (canvas_w - content_w) // 2
    base_y = (canvas_h - content_h) // 2 - VERTICAL_OFFSET

    if side == "left":
        avatar_x = base_x
        bubble_x = base_x + AVATAR_SIZE + AVATAR_GAP
    else:
        bubble_x = base_x
        avatar_x = base_x + bw + AVATAR_GAP

    # ── 头像在内容块顶部 ──
    avatar_y = base_y

    # ── 名字在头像正下方，水平居中 ──
    name_x = avatar_x + (AVATAR_SIZE - nw) // 2
    name_y = avatar_y + AVATAR_SIZE + name_gap

    # ── 气泡与头像顶部对齐 ──
    bubble_y = base_y

    # ── 选择气泡颜色 ──
    bubble_color = BUBBLE_COLOR_SELF if side == "right" else BUBBLE_COLOR_OTHER

    # 绘制名字
    draw.text((name_x, name_y), name, fill=NAME_COLOR, font=name_font)

    # 绘制头像
    if avatar_img:
        frame.paste(avatar_img, (int(avatar_x), int(avatar_y)), avatar_img)

    # 绘制气泡（微信无尾巴）
    draw.rounded_rectangle(
        [bubble_x, bubble_y, bubble_x + bw, bubble_y + bh],
        radius=BUBBLE_RADIUS,
        fill=bubble_color,
    )

    # 绘制文字（alpha 合成：先画满不透明层，再按字符 alpha 乘算）
    pad_l, pad_t = BUBBLE_PAD[0], BUBBLE_PAD[1]
    base_tx = bubble_x + pad_l
    ty = bubble_y + pad_t

    # 先画到透明层（逐字绘制以支持 LETTER_SPACING）
    text_layer = Image.new("RGBA", (canvas_w, canvas_h), (0, 0, 0, 0))
    layer_draw = ImageDraw.Draw(text_layer)
    for line in lines:
        cx = base_tx
        for ch in line:
            layer_draw.text((cx, ty), ch, fill=TEXT_COLOR, font=font)
            cx += layer_draw.textbbox((0, 0), ch, font=font)[2] + LETTER_SPACING
        b = layer_draw.textbbox((0, 0), line, font=font)
        ty += (b[3] - b[1]) + LINE_GAP

    # 逐字对透明层做 alpha 乘法（PIL 不支持在 draw.text 时渐变 alpha）
    if alphas is not None and not all(a >= 1.0 for a in alphas):
        layer_pix = text_layer.load()
        char_x = base_tx
        char_y = bubble_y + pad_t
        line_start = 0
        for line in lines:
            for i, ch in enumerate(line):
                char_idx = line_start + i
                a = alphas[char_idx]
                if a < 1.0:
                    cbox = layer_draw.textbbox((0, 0), ch, font=font)
                    cw = cbox[2] - cbox[0]
                    ch_x = int(char_x + cbox[0])
                    ch_y = int(char_y + cbox[1])
                    ch_w = max(cw, 1)
                    ch_h = max(cbox[3] - cbox[1], 1)
                    for py in range(ch_y, min(ch_y + ch_h + 4, canvas_h)):
                        for px in range(ch_x, min(ch_x + ch_w + 4, canvas_w)):
                            r, g, b, pixel_a = layer_pix[px, py]
                            if pixel_a > 0:
                                layer_pix[px, py] = (r, g, b, int(pixel_a * a))
                char_x += layer_draw.textbbox((0, 0), ch, font=font)[2] + LETTER_SPACING
            # 换行
            char_x = base_tx
            b = layer_draw.textbbox((0, 0), line, font=font)
            char_y += (b[3] - b[1]) + LINE_GAP
            line_start += len(line)

    # 合成到 frame
    frame = Image.alpha_composite(frame, text_layer)

    return frame


def render_quote_clip(
    name,
    text,
    side,
    avatar_img,
    canvas_w=1920,
    canvas_h=1080,
    fps=FPS,
    frames_per_char=FRAMES_PER_CHAR,
    bg_color=None,
):
    """渲染整段话的所有帧，返回帧列表"""
    frames = []
    total_chars = len(text)
    fade_frames = FADE_SPAN * frames_per_char
    # 每个字符首次出现的全局帧号
    char_start = [c * frames_per_char for c in range(total_chars)]

    frame_idx = 0
    for ci in range(1, total_chars + 1):
        visible = text[:ci]
        for _ in range(frames_per_char):
            # 逐字 alpha：按各自出场时间计算
            alphas = [
                min(1.0, (frame_idx - char_start[c] + 1) / fade_frames)
                for c in range(ci)
            ]
            f = render_quote(
                name,
                visible,
                side,
                avatar_img,
                canvas_w,
                canvas_h,
                full_text=text,
                bg_color=bg_color,
                alphas=alphas,
            )
            frames.append(f)
            frame_idx += 1

    # 完整显示后停留一会儿
    full_frame = render_quote(
        name,
        text,
        side,
        avatar_img,
        canvas_w,
        canvas_h,
        full_text=text,
        bg_color=bg_color,
    )
    for _ in range(int(fps * 2)):  # 停留 2 秒
        frames.append(full_frame.copy())

    return frames


def save_frames_to_video(frames, output_path, fps=FPS, transparent=False):
    """将帧列表保存为视频（通过 pipe 直接喂给 ffmpeg，零临时文件）

    transparent=True  → raw rgba  → qtrle 编码 .mov
    transparent=False → raw rgb24 → h264  编码 .mp4
    """
    w, h = frames[0].size

    if transparent:
        pix_fmt_in = "rgba"
        pix_fmt_out = "rgba"
        codec = "qtrle"
    else:
        pix_fmt_in = "rgb24"
        pix_fmt_out = "yuv420p"
        codec = "libx264"

    cmd = [
        "ffmpeg",
        "-y",
        "-f",
        "rawvideo",
        "-pixel_format",
        pix_fmt_in,
        "-video_size",
        f"{w}x{h}",
        "-framerate",
        str(fps),
        "-i",
        "-",  # stdin
        "-c:v",
        codec,
        "-pix_fmt",
        pix_fmt_out,
        "-loglevel",
        "error",
        output_path,
    ]

    proc = subprocess.Popen(cmd, stdin=subprocess.PIPE)
    for frame in frames:
        if not transparent:
            frame = frame.convert("RGB")
        proc.stdin.write(frame.tobytes())
    proc.stdin.close()
    proc.wait()

    return output_path


def parse_input(source):
    """解析输入：文件或文本"""
    if os.path.isfile(source):
        with open(source, "r", encoding="utf-8") as f:
            return f.read().strip()
    return source.strip()


def main():
    parser = argparse.ArgumentParser(description="字幕引用视频生成器")
    parser.add_argument("input", help="输入文本或文件路径（每行: 名字: 内容）")
    parser.add_argument(
        "-o", "--output", default="output", help="输出路径（目录或文件）"
    )
    parser.add_argument("--avatar", help="头像图片路径（所有引用共用）")
    parser.add_argument("--right", action="store_true", help="头像在右侧（默认左侧）")
    parser.add_argument("--width", type=int, default=1920, help="画布宽度")
    parser.add_argument("--height", type=int, default=1080, help="画布高度")
    parser.add_argument("--fps", type=int, default=FPS, help="帧率")
    parser.add_argument(
        "--speed",
        type=int,
        default=FRAMES_PER_CHAR,
        help="每字符帧数（越大打字越慢，默认5=4字/秒）",
    )
    parser.add_argument(
        "--batch", action="store_true", help="批量模式：将 input 文件每行渲染为独立视频"
    )
    parser.add_argument(
        "--transparent", action="store_true", help="透明背景（默认使用微信灰背景）"
    )

    args = parser.parse_args()
    args.input = parse_input(args.input)

    # 背景
    bg_color = None if args.transparent else BG_COLOR
    default_ext = ".mov" if args.transparent else ".mp4"

    # 头像
    avatar_img = load_avatar(args.avatar, AVATAR_SIZE)

    # 解析所有行
    lines = [l.strip() for l in args.input.split("\n") if l.strip()]
    quotes = []
    for line in lines:
        m = re.match(r"^([^:]+):\s*(.*)", line)
        if m:
            name = m.group(1).strip()
            text = m.group(2).strip()
            if text:
                quotes.append((name, text))

    if not quotes:
        print("未找到有效内容，格式：名字: 内容")
        return

    side = "right" if args.right else "left"

    if args.batch or len(quotes) > 1:
        # 批量模式
        os.makedirs(args.output, exist_ok=True)
        for i, (name, text) in enumerate(quotes):
            loc_avatar = avatar_img or make_avatar(name, AVATAR_SIZE)
            frames = render_quote_clip(
                name,
                text,
                side,
                loc_avatar,
                args.width,
                args.height,
                args.fps,
                args.speed,
                bg_color=bg_color,
            )
            out = os.path.join(args.output, f"{i+1:03d}{default_ext}")
            save_frames_to_video(frames, out, args.fps, transparent=args.transparent)
            print(f"  [{i+1}/{len(quotes)}] {name}: {text[:30]}... → {out}")
        print(f"完成，共 {len(quotes)} 段")
    else:
        # 单条模式
        name, text = quotes[0]
        loc_avatar = avatar_img or make_avatar(name, AVATAR_SIZE)
        frames = render_quote_clip(
            name,
            text,
            side,
            loc_avatar,
            args.width,
            args.height,
            args.fps,
            args.speed,
            bg_color=bg_color,
        )
        out = args.output
        if args.transparent:
            # qtrle 编码必须 .mov 容器
            out = os.path.splitext(out)[0] + ".mov"
        elif not any(out.endswith(ext) for ext in (".mp4", ".mov")):
            out += default_ext
        save_frames_to_video(frames, out, args.fps, transparent=args.transparent)
        print(f"→ {out}")


if __name__ == "__main__":
    main()
