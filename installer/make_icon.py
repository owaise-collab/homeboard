"""Build the project's house mark as a Windows ICO without third-party tools."""
from pathlib import Path
import math
import struct
import zlib


def pixels(size):
    scale = size / 256
    strokes = [[(58, 119), (128, 59), (198, 119)],
               [(77, 113), (77, 192), (179, 192), (179, 113)],
               [(111, 192), (111, 143), (145, 143), (145, 192)]]
    result = []
    for y in range(size):
        row = []
        for x in range(size):
            px, py = (x + .5) / scale, (y + .5) / scale
            dx, dy = max(42 - px, 0, px - 214), max(42 - py, 0, py - 214)
            if math.hypot(dx, dy) > 34 or not (8 <= px <= 248 and 8 <= py <= 248):
                row.append((0, 0, 0, 0)); continue
            color = (17, int(132 - py * .10), int(253 - py * .025), 255)
            for line in strokes:
                for (ax, ay), (bx, by) in zip(line, line[1:]):
                    vx, vy = bx - ax, by - ay
                    t = max(0, min(1, ((px - ax) * vx + (py - ay) * vy) / (vx * vx + vy * vy)))
                    if math.hypot(px - ax - t * vx, py - ay - t * vy) <= 5:
                        color = (255, 255, 255, 255)
            row.append(color)
        result.append(row)
    return result


def png(data):
    size = len(data)
    def chunk(kind, value):
        return struct.pack('>I', len(value)) + kind + value + struct.pack('>I', zlib.crc32(kind + value))
    raw = b''.join(b'\0' + bytes(channel for pixel in row for channel in pixel) for row in data)
    return (b'\x89PNG\r\n\x1a\n' + chunk(b'IHDR', struct.pack('>IIBBBBB', size, size, 8, 6, 0, 0, 0))
            + chunk(b'IDAT', zlib.compress(raw, 9)) + chunk(b'IEND', b''))


def dib(data):
    size = len(data)
    raw = bytes(channel for row in reversed(data) for r, g, b, a in row for channel in (b, g, r, a))
    mask_stride = ((size + 31) // 32) * 4
    return struct.pack('<IIIHHIIIIII', 40, size, size * 2, 1, 32, 0, len(raw), 0, 0, 0, 0) + raw + b'\0' * mask_stride * size


def build(destination):
    sizes = [16, 32, 48, 256]
    images = [png(pixels(n)) if n == 256 else dib(pixels(n)) for n in sizes]
    offset = 6 + 16 * len(sizes)
    entries = []
    for size, image in zip(sizes, images):
        entries.append(struct.pack('<BBBBHHII', size % 256, size % 256, 0, 0, 1, 32, len(image), offset))
        offset += len(image)
    Path(destination).write_bytes(struct.pack('<HHH', 0, 1, len(sizes)) + b''.join(entries) + b''.join(images))


if __name__ == '__main__':
    build(Path(__file__).with_name('homeboard.ico'))
