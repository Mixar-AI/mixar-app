# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-3.0-or-later

"""Compare real captured faces, excluding the animated chip glow."""

import json
from itertools import combinations
from PIL import Image, ImageDraw


def eye_components(mask, width):
    """Connected irises, independent of head tilt and pupil position."""
    remaining = {i for i, lit in enumerate(mask) if lit}
    sizes = []
    while remaining:
        stack = [remaining.pop()]
        area = 0
        while stack:
            index = stack.pop()
            area += 1
            x, y = index % width, index // width
            for dx, dy in ((-1, 0), (1, 0), (0, -1), (0, 1),
                           (-1, -1), (-1, 1), (1, -1), (1, 1)):
                neighbor = (y + dy) * width + x + dx
                if 0 <= x + dx < width and neighbor in remaining:
                    remaining.remove(neighbor)
                    stack.append(neighbor)
        sizes.append(area)
    return sorted(sizes, reverse=True)[:2]


def verify_balanced_eyes(frames):
    pairs = []
    for frame in frames:
        with Image.open(frame['path']) as image:
            # Exclude even the brightest green chip pulse, plus white highlights.
            mask = [g > 125 and g > 4*r and g > 2*b
                    for r, g, b in image.convert('RGB').getdata()]
            pairs.append(eye_components(mask, image.width))
    peak = max(sum(pair) for pair in pairs)
    opened = [pair for pair in pairs if sum(pair) > peak * .70]
    assert len(opened) >= 8, 'Too few open-eyed frames for a visual balance check'
    assert all(len(pair) == 2 and pair[1] >= 8 for pair in opened), 'Missing one iris'
    ratios = [pair[1] / pair[0] for pair in opened]
    assert min(ratios) >= .78, f'One eye is visibly compressed: {min(ratios):.2f}'
    return dict(open_frames=len(opened), minimum_eye_area_ratio=round(min(ratios), 3))


def compare_faces(out):
    names = ['idle', 'thinking', 'reading', 'working', 'generating',
             'responding', 'waiting-for-you', 'listening', 'connecting', 'offline']
    samples, masks, representatives = {}, {}, {}
    for name in names:
        frames = json.loads((out/name/'samples.json').read_text())
        frames = frames[8:]  # Exclude expression transition and capture setup.
        eyes = []
        for frame in frames:
            with Image.open(frame['path']) as image:
                pixels = image.convert('RGB').getdata()
                # Emerald irises have almost no red; the chip has red.
                mask = tuple(g > 125 and g > 4*r and g > 2*b for r, g, b in pixels)
            eyes.append(mask)
        areas = [sum(mask) for mask in eyes]
        assert min(areas) < max(areas)
        masks[name] = [sum(pixel)/len(eyes) for pixel in zip(*eyes)]
        # An open-eyed representative; never make blink coincidence a state cue.
        target_area = sorted(areas)[int(.75*(len(areas)-1))]
        index = min(range(len(eyes)), key=lambda i: abs(areas[i]-target_area))
        representatives[name] = Image.open(frames[index]['path']).convert('RGB')
        samples[name] = frames
    separations = {}
    for a, b in combinations(names, 2):
        separation = sum(abs(x-y) for x,y in zip(masks[a],masks[b])) / 4  # Logical pixels, retina2×.
        separations[a+' / '+b] = round(separation, 2)
        # Activity can differ by gaze rhythm. Never require a deformed eye
        # silhouette merely to distinguish every pair of paused frames.
    # Both actual-size and 2× versions: magnification cannot substitute for1× review.
    sheet = Image.new('RGB', (600, 272), '#191919')
    draw = ImageDraw.Draw(sheet)
    for i, name in enumerate(names):
        x, y = (i % 5)*120, (i//5)*135
        draw.text((x+4, y+4), name.replace('-', ' '), fill='#eeeeee')
        image = representatives[name]
        sheet.paste(image.resize((image.width//2, image.height//2), Image.Resampling.LANCZOS),
                    (x+34, y+22))
        sheet.paste(image, (x+14, y+60))
    sheet.save(out/'comparison.png')
    timeline = []
    for index in range(55):
        frame = Image.new('RGB', (600, 150), '#191919')
        draw = ImageDraw.Draw(frame)
        for i, name in enumerate(names):
            sample = samples[name][index % len(samples[name])]
            image = Image.open(sample['path']).convert('RGB')
            x, y = (i % 5)*120, (i//5)*75
            draw.text((x+4, y+4), name.replace('-', ' '), fill='#eeeeee')
            frame.paste(image.resize((image.width//2,image.height//2), Image.Resampling.LANCZOS),
                        (x+34,y+24))
        timeline.append(frame)
    timeline[0].save(out/'comparison.gif', save_all=True, append_images=timeline[1:],
                     duration=40, loop=0)
    return {'minimum_pairwise_eye_difference_logical_pixels': min(separations.values()),
            'pairwise_eye_differences': separations}
