import asyncio
from PIL import Image, ImageDraw, ImageFont
from datetime import datetime
from light_discord import DiscordBot
from tools import path_from_app_root

#Move center cropping of image to here and save as a temp png
def center_crop_image(input_img_path: str, output_img_path: str) -> str:
    img = Image.open(input_img_path)
    w, h = img.size
    side = min(w, h)
    img_cropped = img.crop(((w - side)//2, (h - side)//2, (w + side)//2, (h + side)//2))
    img_cropped.save(output_img_path)
    return output_img_path

def make_meme(input_img_path: str, caption: str, font: str) -> str:
    media_dir = path_from_app_root("media")
    media_dir.mkdir(exist_ok=True)
    memes_output_dir = media_dir / "memes"
    memes_output_dir.mkdir(exist_ok=True)
    #create meme name using datetime
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    output_path = memes_output_dir / f"meme_{timestamp}.png"

    # === 1. Meme canvas ===
    canvas_width = 1000
    canvas_height = 1200
    meme = Image.new("RGB", (canvas_width, canvas_height), "black")
    draw = ImageDraw.Draw(meme)

    # === 2. White frame settings ===
    border_thickness = 10   # thick border
    frame_margin = 100      # distance from edge of canvas to frame
    frame_top = 50          # distance from top canvas edge to top frame
    frame_bottom = 900      # bottom edge of frame

    # Coordinates of the outer frame
    left = frame_margin
    top = frame_top
    right = canvas_width - frame_margin
    bottom = frame_bottom

    # Draw the thick white border manually (so all sides are visible)
    # Top border
    draw.rectangle([left, top, right, top + border_thickness], fill="white")
    # Bottom border
    draw.rectangle([left, bottom - border_thickness, right, bottom], fill="white")
    # Left border
    draw.rectangle([left, top, left + border_thickness, bottom], fill="white")
    # Right border
    draw.rectangle([right - border_thickness, top, right, bottom], fill="white")

    # === 3. Place center image ===
    # Inner area of frame (where the image goes)
    inner_left = left + border_thickness
    inner_top = top + border_thickness
    inner_right = right - border_thickness
    inner_bottom = bottom - border_thickness

    inner_w = inner_right - inner_left
    inner_h = inner_bottom - inner_top

    # Open and crop input image to a square
    img = Image.open(input_img_path)
    w, h = img.size
    side = min(w, h)
    img_cropped = img.crop(((w - side)//2, (h - side)//2, (w + side)//2, (h + side)//2))
    img_cropped = img_cropped.resize((inner_w, inner_h))

    meme.paste(img_cropped, (inner_left, inner_top))

    # === 4. Add caption ===
    caption = caption.upper()

    # Helper: wrap text into lines that fit max_width using given font
    def wrap_text(text, draw_obj, font_obj, max_w):
        words = text.split()
        if not words:
            return [""]
        lines = []
        cur = words[0]
        for w in words[1:]:
            test = cur + " " + w
            bbox = draw_obj.textbbox((0, 0), test, font=font_obj)
            if (bbox[2] - bbox[0]) <= max_w:
                cur = test
            else:
                lines.append(cur)
                cur = w
        lines.append(cur)
        return lines

    # Try different font sizes until text fits within the available caption area
    max_caption_width = inner_w - 40  # leave some horizontal padding
    caption_top_margin = 40
    caption_bottom_margin = 20
    text_start_y = frame_bottom + caption_top_margin
    max_caption_height = canvas_height - text_start_y - caption_bottom_margin

    # Load an initial font size and then reduce if needed
    starting_size = 60
    min_size = 18
    chosen_font = None
    wrapped_lines = [caption]
    used_size = starting_size

    for size in range(starting_size, min_size - 1, -2):
        try:
            fnt = ImageFont.truetype(font, size)
        except Exception:
            try:
                fnt = ImageFont.truetype("impact.ttf", size)
            except Exception:
                fnt = ImageFont.load_default()

        lines = wrap_text(caption, draw, fnt, max_caption_width)
        # compute total height
        line_heights = []
        max_line_w = 0
        for ln in lines:
            bb = draw.textbbox((0, 0), ln, font=fnt)
            w = bb[2] - bb[0]
            h = bb[3] - bb[1]
            line_heights.append(h)
            if w > max_line_w:
                max_line_w = w
        total_h = sum(line_heights) + (len(lines) - 1) * int(size * 0.1)

        if max_line_w <= max_caption_width and total_h <= max_caption_height:
            chosen_font = fnt
            wrapped_lines = lines
            used_size = size
            break

    # Fallback: if nothing fits, use the smallest available font and possibly truncate lines
    if chosen_font is None:
        try:
            chosen_font = ImageFont.truetype(font, min_size)
        except Exception:
            try:
                chosen_font = ImageFont.truetype("impact.ttf", min_size)
            except Exception:
                chosen_font = ImageFont.load_default()
        wrapped_lines = wrap_text(caption, draw, chosen_font, max_caption_width)

    # Compute starting positions and draw each line centered
    # Compute line heights again for placement
    line_sizes = [draw.textbbox((0, 0), ln, font=chosen_font) for ln in wrapped_lines]
    line_widths = [bb[2] - bb[0] for bb in line_sizes]
    line_heights = [bb[3] - bb[1] for bb in line_sizes]
    line_spacing = int(used_size * 0.1)
    total_text_height = sum(line_heights) + (len(line_heights) - 1) * line_spacing

    # start y so block fits within available area (top aligned to text_start_y)
    start_y = text_start_y
    # If there's extra vertical space, keep top margin; we could center if desired

    # Draw outline + main text for each line
    for idx, ln in enumerate(wrapped_lines):
        tw = line_widths[idx]
        th = line_heights[idx]
        text_x = (canvas_width - tw) // 2
        text_y = start_y + sum(line_heights[:idx]) + idx * line_spacing
        for dx, dy in [(-3, -3), (-3, 3), (3, -3), (3, 3)]:
            draw.text((text_x + dx, text_y + dy), ln, font=chosen_font, fill="black")
        draw.text((text_x, text_y), ln, font=chosen_font, fill="white")

    meme.save(output_path)
    return output_path


# Example:
if __name__ == "__main__":
    import re
    from openai_chat import OpenAiManager
    chatGPT = OpenAiManager()
    discord_bot = DiscordBot()
    discord_bot.start_bot_background()
    print("Analyzing image for meme caption and font...")
    response = chatGPT.analyze_image("test_image.jpg", True)
    print(response)
    caption_match = re.search(r'!caption\s*(.*?)\s*(?=!font|$)', response, re.DOTALL | re.IGNORECASE)
    font_match = re.search(r'!font\s*(.*?)\s*(?=!caption|$)', response, re.DOTALL | re.IGNORECASE)
    if caption_match:
        parsed_caption = caption_match.group(1).strip()
        print(f"Parsed Caption: {parsed_caption}")
    if font_match:
        parsed_font = font_match.group(1).strip()
        print(f"Parsed Font: {parsed_font}")
    print("Creating meme...")
    meme = make_meme("test_image.jpg", parsed_caption, parsed_font)
    asyncio.run(discord_bot.send_image(759165114657013815, meme))
