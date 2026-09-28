import asyncio
import mmap
import struct
import zlib
from pathlib import Path

from PIL import Image


# ============================================================
# CONFIG
# ============================================================

HOST = "IP or Domain"
PORT = 7777

VERSION = "Terraria326"
PLAYER_NAME = "bBot"

WORLD_DIR = Path("terraria_world")

TILES_FILE = WORLD_DIR / "tiles.bin"
WALLS_FILE = WORLD_DIR / "walls.bin"
LIQUIDS_FILE = WORLD_DIR / "liquids.bin"
PAINT_FILE = WORLD_DIR / "paint.bin"
META_FILE = WORLD_DIR / "metadata.bin"
FRAMES_FILE = WORLD_DIR / "frames.bin"

PNG_FILE = Path("terraria_map.png")
LEGEND_FILE = Path("terraria_map_legend.txt")

SECTION_WIDTH = 200
SECTION_HEIGHT = 150

MOVE_DELAY = 0.35

SCAN_WHOLE_WORLD = True


# ============================================================
# FRAME IMPORTANT
# ============================================================

FRAME_IMPORTANT = (
    0x2086041EBD3FFC38,
    0x600647FFFFFEE780,
    0x0F0478200021EFF3,
    0x40FFFA981F968200,
    0xF47FFFFFEFF8E000,
    0x17F01FDC200EC019,
    0x3FF83B987C600FFC,
    0xE60A6FF118FFE3F0,
    0x3FB1DFFBC43EFFC0,
    0xA5E1FBFFFFFFFFF8,
    0xFDE0000003977FFD,
    0x00038000207B1FEF,
)

TILE_COUNT = 754


def frame_important(tile_id):
    """Check whether a tile contains frame X/Y."""

    if tile_id < 0 or tile_id >= TILE_COUNT:
        return False

    index = tile_id >> 6
    bit = tile_id & 63

    return bool(
        (FRAME_IMPORTANT[index] >> bit) & 1
    )


# ============================================================
# TERRARIA STRING
# ============================================================

def write_string(text):
    """Encode Terraria 7-bit string."""

    data = text.encode("utf-8")

    result = bytearray()
    value = len(data)

    while value >= 0x80:
        result.append(
            (value & 0x7F) | 0x80
        )
        value >>= 7

    result.append(value)
    result.extend(data)

    return bytes(result)


def read_string(data, pos):
    """Decode Terraria 7-bit string."""

    length = 0
    shift = 0

    while True:
        if pos >= len(data):
            raise ValueError(
                "Unexpected end of string"
            )

        value = data[pos]
        pos += 1

        length |= (
            (value & 0x7F)
            << shift
        )

        if not value & 0x80:
            break

        shift += 7

        if shift > 35:
            raise ValueError(
                "Invalid 7-bit string"
            )

    end = pos + length

    if end > len(data):
        raise ValueError(
            "String exceeds packet"
        )

    text = data[pos:end].decode(
        "utf-8",
        errors="replace",
    )

    return text, end


# ============================================================
# PACKETS
# ============================================================

def make_packet(packet_id, payload=b""):
    """Build Terraria packet."""

    body = bytes([packet_id]) + payload

    return (
        struct.pack(
            "<H",
            len(body) + 2,
        )
        + body
    )


async def send_packet(
    writer,
    packet_id,
    payload=b"",
):
    """Send one Terraria packet."""

    writer.write(
        make_packet(
            packet_id,
            payload,
        )
    )

    await writer.drain()


async def read_packet(reader):
    """Read one Terraria packet."""

    header = await reader.readexactly(2)

    length = struct.unpack(
        "<H",
        header,
    )[0]

    if length < 3:
        raise ValueError(
            f"Invalid packet length: {length}"
        )

    body = await reader.readexactly(
        length - 2
    )

    return body[0], body[1:]


# ============================================================
# PLAYER INFO
# ============================================================

async def send_player_info(
    writer,
    player_id,
):
    """Send PlayerInfo using the working handshake layout."""

    payload = bytearray()

    payload.append(player_id)
    payload.append(0)
    payload.append(1)
    payload.extend(struct.pack("<f", 0.0))
    payload.append(0)
    payload.extend(write_string(PLAYER_NAME))
    payload.append(0)
    payload.extend(struct.pack("<H", 0))
    payload.append(0)

    payload.extend((120, 80, 60))
    payload.extend((255, 200, 170))
    payload.extend((0, 0, 0))
    payload.extend((100, 100, 100))
    payload.extend((150, 150, 150))
    payload.extend((50, 50, 50))
    payload.extend((40, 40, 40))

    payload.append(0)
    payload.append(0)
    payload.append(0)

    await send_packet(writer, 4, bytes(payload))
    print("[>] PlayerInfo sent")


async def send_inventory(
    writer,
    player_id,
):
    """Send 59 empty inventory slots."""

    for slot in range(59):

        payload = bytearray()

        payload.append(player_id)
        payload.extend(struct.pack("<h", slot))
        payload.extend(struct.pack("<h", 0))
        payload.append(0)
        payload.extend(struct.pack("<h", 0))
        payload.append(0)

        await send_packet(writer, 5, bytes(payload))

    print("[>] Inventory sent")


async def request_world(writer):
    """Request WorldInfo."""

    await send_packet(writer, 6)
    print("[>] WorldInfo requested")


async def request_essential_tiles(writer, x, y):
    """Request initial world section around spawn."""

    await send_packet(
        writer,
        8,
        struct.pack("<ii", int(x), int(y)),
    )

    print("[>] Initial tile request sent")


async def send_spawn_player(writer, player_id, x, y):
    """Send Packet 12."""

    payload = bytearray()

    payload.append(player_id)
    payload.extend(struct.pack("<h", int(x)))
    payload.extend(struct.pack("<h", int(y)))
    payload.extend(struct.pack("<h", 0))
    payload.extend(struct.pack("<h", 0))
    payload.extend(struct.pack("<i", 0))
    payload.append(1)

    await send_packet(writer, 12, bytes(payload))


async def send_update_player(writer, player_id, tile_x, tile_y):
    """Send Packet 13 using tile coordinates."""

    payload = bytearray()

    payload.append(player_id)
    payload.append(0)
    payload.append(0)
    payload.append(0)
    payload.append(0)
    payload.append(0)

    payload.extend(
        struct.pack(
            "<ff",
            float(tile_x * 16),
            float(tile_y * 16),
        )
    )

    await send_packet(writer, 13, bytes(payload))


# ============================================================
# WORLD STORAGE
# ============================================================

class WorldMap:
    """Disk-backed Terraria world."""

    def __init__(self, width, height):

        self.width = width
        self.height = height
        self.total_tiles = width * height

        self.section_columns = (
            width + SECTION_WIDTH - 1
        ) // SECTION_WIDTH

        self.section_rows = (
            height + SECTION_HEIGHT - 1
        ) // SECTION_HEIGHT

        self.sections = set()

        WORLD_DIR.mkdir(parents=True, exist_ok=True)

        print()
        print("[*] Creating world storage")
        print(f"[*] Size: {width} x {height}")
        print(f"[*] Tiles: {self.total_tiles:,}")

        self.files = {}
        self.maps = {}

        specs = {
            "tiles":    (TILES_FILE,   2),
            "walls":    (WALLS_FILE,   2),
            "liquids":  (LIQUIDS_FILE, 2),
            "paint":    (PAINT_FILE,   2),
            "metadata": (META_FILE,    1),
            "frames":   (FRAMES_FILE,  4),
        }

        for name, (path, bytes_per_tile) in specs.items():

            size = self.total_tiles * bytes_per_tile

            file = open(path, "w+b")
            file.truncate(size)

            self.files[name] = file
            self.maps[name] = mmap.mmap(
                file.fileno(),
                size,
            )

        print("[+] Storage ready")

    def add_section(
        self,
        start_x,
        start_y,
        width,
        height,
        tiles,
    ):
        """Write decoded section to mmap files."""

        key = (start_x, start_y)

        if key in self.sections:
            return False

        if start_x < 0 or start_y < 0:
            return False

        if start_x >= self.width:
            return False

        if start_y >= self.height:
            return False

        width = min(width, self.width - start_x)
        height = min(height, self.height - start_y)

        if len(tiles) < width * height:
            return False

        tiles_map = self.maps["tiles"]
        walls_map = self.maps["walls"]
        liquids_map = self.maps["liquids"]
        paint_map = self.maps["paint"]
        meta_map = self.maps["metadata"]
        frames_map = self.maps["frames"]

        for row in range(height):

            section_row = row * width

            world_row = (
                (start_y + row) * self.width
                + start_x
            )

            for col in range(width):

                tile = tiles[section_row + col]
                world_index = world_row + col
                offset = world_index * 2

                struct.pack_into(
                    "<H", tiles_map, offset,
                    tile["tile_id"],
                )

                struct.pack_into(
                    "<H", walls_map, offset,
                    tile["wall_id"],
                )

                liquid_value = (
                    tile["liquid_amount"]
                    | (tile["liquid_type"] << 8)
                )

                struct.pack_into(
                    "<H", liquids_map, offset,
                    liquid_value,
                )

                paint_value = (
                    tile["tile_paint"]
                    | (tile["wall_paint"] << 8)
                )

                struct.pack_into(
                    "<H", paint_map, offset,
                    paint_value,
                )

                meta = tile["brick_style"] & 0x07

                if tile["half_block"]:
                    meta |= 1 << 3
                if tile["actuator"]:
                    meta |= 1 << 4
                if tile["inactive"]:
                    meta |= 1 << 5
                if tile["invisible_block"]:
                    meta |= 1 << 6
                if tile["invisible_wall"]:
                    meta |= 1 << 7

                meta_map[world_index] = meta

                frame_value = (
                    (tile["frame_x"] & 0xFFFF)
                    | ((tile["frame_y"] & 0xFFFF) << 16)
                )

                struct.pack_into(
                    "<I", frames_map, world_index * 4,
                    frame_value,
                )

        self.sections.add(key)

        if len(self.sections) % 5 == 0:
            self.flush()

        return True

    def flush(self):
        for mapping in self.maps.values():
            mapping.flush()

    def close(self):
        try:
            self.flush()
        except Exception:
            pass

        for mapping in self.maps.values():
            mapping.close()

        for file in self.files.values():
            file.close()


# ============================================================
# TILE DECODER
# ============================================================

def decode_tile(data, pos):
    """Decode one Terraria tile."""

    if pos >= len(data):
        raise ValueError("Tile data ended early")

    flags1 = data[pos]
    pos += 1

    flags2 = 0
    flags3 = 0
    flags4 = 0

    if flags1 & 0x01:
        if pos >= len(data):
            raise ValueError("Missing header 2")
        flags2 = data[pos]
        pos += 1

        if flags2 & 0x01:
            if pos >= len(data):
                raise ValueError("Missing header 3")
            flags3 = data[pos]
            pos += 1

            if flags3 & 0x01:
                if pos >= len(data):
                    raise ValueError("Missing header 4")
                flags4 = data[pos]
                pos += 1

    active = bool(flags1 & 0x02)

    tile_id = 0
    frame_x = 0
    frame_y = 0

    if active:
        if pos >= len(data):
            raise ValueError("Missing tile ID")
        tile_id = data[pos]
        pos += 1

        if flags1 & 0x20:
            if pos >= len(data):
                raise ValueError("Missing tile ID high byte")
            tile_id |= data[pos] << 8
            pos += 1

        if frame_important(tile_id):
            if pos + 4 > len(data):
                raise ValueError("Missing tile frame")

            frame_x = struct.unpack_from(
                "<h", data, pos,
            )[0]
            pos += 2

            frame_y = struct.unpack_from(
                "<h", data, pos,
            )[0]
            pos += 2

    wall_id = 0

    if flags1 & 0x04:
        if pos >= len(data):
            raise ValueError("Missing wall ID")
        wall_id = data[pos]
        pos += 1

        if flags3 & 0x40:
            if pos >= len(data):
                raise ValueError("Missing wall high byte")
            wall_id |= data[pos] << 8
            pos += 1

    liquid_amount = 0
    liquid_type = 0

    liquid_bits = flags1 & 0x18

    if liquid_bits:
        if pos >= len(data):
            raise ValueError("Missing liquid amount")

        if liquid_bits == 0x08:
            liquid_type = 1
            if flags3 & 0x80:
                liquid_type = 4
        elif liquid_bits == 0x10:
            liquid_type = 2
        elif liquid_bits == 0x18:
            liquid_type = 3

        liquid_amount = data[pos]
        pos += 1

    tile_paint = 0
    wall_paint = 0

    if flags3 & 0x08:
        if pos >= len(data):
            raise ValueError("Missing tile paint")
        tile_paint = data[pos]
        pos += 1

    if flags3 & 0x10:
        if pos >= len(data):
            raise ValueError("Missing wall paint")
        wall_paint = data[pos]
        pos += 1

    brick_style = (flags2 >> 4) & 0x07
    half_block = (brick_style == 1)

    actuator = bool(flags3 & 0x02)
    inactive = bool(flags3 & 0x04)
    invisible_block = bool(flags4 & 0x02)
    invisible_wall = bool(flags4 & 0x04)
    fullbright_block = bool(flags4 & 0x08)
    fullbright_wall = bool(flags4 & 0x10)

    run = 0

    if flags1 & 0x40:
        if pos >= len(data):
            raise ValueError("Missing RLE byte")
        run = data[pos]
        pos += 1

    elif flags1 & 0x80:
        if pos + 2 > len(data):
            raise ValueError("Missing RLE ushort")
        run = struct.unpack_from("<H", data, pos)[0]
        pos += 2

    return (
        {
            "tile_id": tile_id,
            "wall_id": wall_id,
            "liquid_amount": liquid_amount,
            "liquid_type": liquid_type,
            "tile_paint": tile_paint,
            "wall_paint": wall_paint,
            "frame_x": frame_x,
            "frame_y": frame_y,
            "brick_style": brick_style,
            "half_block": half_block,
            "actuator": actuator,
            "inactive": inactive,
            "invisible_block": invisible_block,
            "invisible_wall": invisible_wall,
            "fullbright_block": fullbright_block,
            "fullbright_wall": fullbright_wall,
        },
        run,
        pos,
    )


# ============================================================
# SECTION PARSER
# ============================================================

def parse_section(payload):
    """Decode Terraria Packet 10."""

    try:
        data = zlib.decompress(payload, -zlib.MAX_WBITS)
    except zlib.error:
        data = zlib.decompress(payload)

    if len(data) < 12:
        raise ValueError("Section payload too short")

    pos = 0

    start_x = struct.unpack_from("<i", data, pos)[0]
    pos += 4

    start_y = struct.unpack_from("<i", data, pos)[0]
    pos += 4

    width = struct.unpack_from("<h", data, pos)[0]
    pos += 2

    height = struct.unpack_from("<h", data, pos)[0]
    pos += 2

    if width <= 0 or height <= 0:
        raise ValueError(f"Invalid section size {width}x{height}")

    if width > SECTION_WIDTH:
        raise ValueError(f"Section width too large: {width}")

    if height > SECTION_HEIGHT:
        raise ValueError(f"Section height too large: {height}")

    total = width * height
    tiles = []
    append_tile = tiles.append

    while len(tiles) < total:
        tile, run, pos = decode_tile(data, pos)
        count = min(run + 1, total - len(tiles))
        for _ in range(count):
            append_tile(tile)

    return start_x, start_y, width, height, tiles


# ============================================================
# WORLD INFO
# ============================================================

def parse_world_info(payload):
    """Parse the WorldInfo packet."""

    pos = 0

    if len(payload) < 24:
        raise ValueError("WorldInfo packet too short")

    pos += 4
    pos += 1
    pos += 1

    width = struct.unpack_from("<h", payload, pos)[0]
    pos += 2

    height = struct.unpack_from("<h", payload, pos)[0]
    pos += 2

    spawn_x = struct.unpack_from("<h", payload, pos)[0]
    pos += 2

    spawn_y = struct.unpack_from("<h", payload, pos)[0]
    pos += 2

    surface = struct.unpack_from("<h", payload, pos)[0]
    pos += 2

    rock_layer = struct.unpack_from("<h", payload, pos)[0]
    pos += 2

    world_id = struct.unpack_from("<i", payload, pos)[0]
    pos += 4

    name, pos = read_string(payload, pos)

    if pos >= len(payload):
        raise ValueError("Missing game mode")

    game_mode = payload[pos]
    pos += 1

    world_uuid = b""

    if pos + 16 <= len(payload):
        world_uuid = payload[pos:pos + 16]
        pos += 16

    return {
        "width": width,
        "height": height,
        "spawn_x": spawn_x,
        "spawn_y": spawn_y,
        "surface": surface,
        "rock_layer": rock_layer,
        "world_id": world_id,
        "name": name,
        "game_mode": game_mode,
        "world_uuid": world_uuid,
    }


# ============================================================
# TILE COLORS  (complete & tuned)
# ============================================================

TILE_COLORS = {
    # ---------- پایه ----------
    0:   (151, 107, 75),    # Dirt
    1:   (128, 128, 128),   # Stone
    2:   (63, 150, 63),     # Grass
    3:   (76, 175, 76),     # Plants
    4:   (240, 200, 90),    # Torch
    5:   (139, 96, 62),     # Tree
    6:   (140, 140, 150),   # Iron
    7:   (184, 115, 51),    # Copper
    8:   (218, 165, 55),    # Gold
    9:   (200, 200, 210),   # Silver
    10:  (140, 100, 70),    # Door closed
    11:  (150, 110, 80),    # Door open
    12:  (255, 90, 150),    # Heart Crystal
    13:  (80, 60, 40),      # Bottle
    14:  (150, 110, 70),    # Table
    15:  (140, 100, 60),    # Chair
    16:  (100, 100, 110),   # Anvil
    17:  (90, 90, 100),     # Furnace
    18:  (160, 120, 80),    # Work Bench
    19:  (160, 120, 80),    # Platform
    20:  (140, 100, 70),    # Sapling
    21:  (230, 185, 70),    # Chest
    22:  (110, 110, 160),   # Demonite
    23:  (103, 78, 125),    # Corrupt grass
    24:  (83, 145, 67),     # Corrupt plants
    25:  (112, 80, 130),    # Ebonstone
    26:  (95, 55, 130),     # Demon Altar
    27:  (110, 90, 130),    # Sunflower
    28:  (110, 90, 130),    # Pot
    29:  (110, 90, 130),    # Piggy Bank
    30:  (151, 107, 75),    # Wood
    31:  (150, 70, 200),    # Shadow Orb / Crimson Heart

    # ---------- آجرها ----------
    38:  (100, 100, 110),
    39:  (110, 110, 120),
    40:  (90, 90, 100),
    41:  (100, 100, 130),   # Blue Dungeon
    42:  (100, 130, 100),   # Green Dungeon
    43:  (140, 100, 140),   # Pink Dungeon

    # ---------- Hell ----------
    57:  (134, 61, 43),     # Hellstone brick
    58:  (230, 100, 50),    # Hellstone ore

    # ---------- Jungle ----------
    59:  (78, 145, 67),     # Jungle grass
    60:  (69, 132, 61),     # Jungle plants
    61:  (90, 120, 60),     # Jungle vines
    62:  (110, 80, 55),     # Jungle thorn

    # ---------- Meteor / Obsidian ----------
    37:  (90, 80, 110),     # Meteorite
    75:  (60, 55, 75),      # Obsidian

    # ---------- Cactus / Sand ----------
    53:  (218, 198, 134),   # Sand

    # ---------- Corruption ----------
    109: (188, 111, 190),   # Hallowed grass
    110: (168, 94, 180),    # Hallowed plants
    112: (90, 70, 120),     # Ebonsand

    # ---------- Pearl / Snow / Ice ----------
    116: (230, 230, 245),   # Pearlsand
    147: (245, 248, 252),   # Snow Block
    148: (235, 240, 248),   # Snow Brick
    149: (240, 245, 250),   # Snow Platform
    150: (200, 210, 225),   # Ice (thin)
    161: (185, 225, 245),   # Ice Block
    162: (170, 215, 240),   # Ice Brick
    163: (185, 225, 245),   # Ice Platform

    # ---------- Cloud / Rain ----------
    189: (250, 250, 255),   # Cloud
    190: (170, 175, 195),   # Rain Cloud
    196: (215, 225, 245),   # Snow Cloud

    # ---------- Crimson ----------
    199: (155, 48, 53),
    200: (170, 56, 60),     # Crimson grass
    203: (145, 45, 48),     # Crimstone
    204: (125, 38, 42),     # Crimtane

    # ---------- Hardmode ----------
    211: (100, 220, 150),   # Chlorophyte
    212: (140, 90, 60),     # Titanium
    213: (90, 130, 180),    # Adamantite
    214: (200, 200, 220),   # Palladium
    215: (150, 150, 100),   # Orichalcum
    216: (130, 190, 220),   # Mythril

    # ---------- Lihzahrd ----------
    226: (180, 150, 100),   # Lihzahrd Brick
    227: (255, 140, 60),    # Life Fruit
    237: (255, 200, 80),    # Lihzahrd Altar
    238: (140, 255, 100),   # Plantera's Bulb
    239: (200, 130, 80),    # Spooky wood

    # ---------- Enchanted Sword ----------
    186: (140, 220, 255),   # Enchanted Sword in Stone
    187: (140, 220, 255),   # Enchanted Sword (alt)

    # ---------- Pyramids ----------
    151: (200, 180, 130),   # Pyramid brick
    152: (200, 180, 130),
    153: (200, 180, 130),

    # ---------- Living wood / leaf ----------
    191: (110, 80, 55),     # Living Wood
    192: (100, 200, 90),    # Leaf
    193: (110, 80, 55),     # Living Wood Wall

    # ---------- Bricks ----------
    221: (150, 130, 110),   # Sandstone
    222: (150, 130, 110),
}


# ============================================================
# WALL COLORS
# ============================================================

WALL_COLORS = {
    1:   (105, 80, 60),
    2:   (95, 95, 95),
    3:   (75, 65, 55),
    4:   (105, 75, 50),
    5:   (80, 80, 85),
    6:   (110, 60, 60),
    7:   (90, 55, 90),
    8:   (75, 50, 85),
    9:   (70, 70, 75),
    10:  (115, 85, 60),
    11:  (100, 80, 55),
    12:  (90, 70, 50),
    13:  (140, 110, 70),
    14:  (120, 100, 70),
    15:  (85, 60, 45),
    16:  (70, 55, 45),
    17:  (60, 60, 70),
    18:  (90, 110, 90),
    19:  (110, 100, 90),
    20:  (100, 90, 80),
    21:  (120, 105, 75),
    22:  (100, 80, 70),
    23:  (90, 60, 100),
    24:  (95, 50, 105),
    25:  (120, 100, 80),
    26:  (100, 90, 80),
    27:  (200, 210, 220),   # Cloud wall
    28:  (150, 155, 175),   # Rain cloud wall
    29:  (80, 90, 100),
    30:  (120, 90, 60),
    40:  (180, 200, 220),   # Ice wall
    41:  (90, 90, 90),
    44:  (160, 140, 100),
    45:  (120, 120, 120),
}


# ============================================================
# PAINT COLORS
# ============================================================

PAINT_COLORS = {
    0:   (255, 255, 255),
    1:   (255, 0, 0),
    2:   (255, 127, 0),
    3:   (255, 255, 0),
    4:   (127, 255, 0),
    5:   (0, 255, 0),
    6:   (0, 255, 127),
    7:   (0, 255, 255),
    8:   (0, 127, 255),
    9:   (0, 0, 255),
    10:  (127, 0, 255),
    11:  (191, 0, 255),
    12:  (255, 0, 127),
    13:  (127, 0, 0),
    14:  (127, 63, 0),
    15:  (127, 127, 0),
    16:  (63, 127, 0),
    17:  (0, 127, 0),
    18:  (0, 127, 63),
    19:  (0, 127, 127),
    20:  (0, 63, 127),
    21:  (0, 0, 127),
    22:  (63, 0, 127),
    23:  (95, 0, 127),
    24:  (127, 0, 63),
    25:  (0, 0, 0),         # Deep red
    26:  (255, 255, 255),   # Deep white
    27:  (128, 128, 128),   # Deep gray
    28:  (127, 63, 31),     # Deep brown
    29:  (0, 0, 0),         # Shadow
    30:  (255, 255, 255),   # Negative (special)
    31:  (255, 255, 255),   # Illuminant
}


# ============================================================
# LIQUID COLORS
# ============================================================

LIQUID_COLORS = {
    1: (52, 125, 220),   # Water
    2: (230, 70, 25),    # Lava
    3: (225, 155, 45),   # Honey
    4: (160, 80, 225),   # Shimmer
}


# ============================================================
# HIGHLIGHT TILES
# آیتم‌های مهم که باید روی نقشه خودنمایی کنن
# ============================================================

HIGHLIGHT_TILES = {
    12:  (255, 80, 150),    # Heart Crystal
    21:  (255, 220, 60),    # Chest
    26:  (200, 80, 255),    # Demon Altar
    31:  (180, 60, 220),    # Shadow Orb / Crimson Heart
    186: (120, 220, 255),   # Enchanted Sword in Stone
    187: (120, 220, 255),   # Enchanted Sword in Stone (alt)
    227: (255, 140, 60),    # Life Fruit
    237: (255, 200, 80),    # Lihzahrd Altar
    238: (140, 255, 100),   # Plantera's Bulb
}


LEGEND_ENTRIES = [
    ("Heart Crystal",       (255, 80, 150)),
    ("Chest",               (255, 220, 60)),
    ("Demon Altar",         (200, 80, 255)),
    ("Shadow Orb / Heart",  (180, 60, 220)),
    ("Enchanted Sword",     (120, 220, 255)),
    ("Life Fruit",          (255, 140, 60)),
    ("Lihzahrd Altar",      (255, 200, 80)),
    ("Plantera's Bulb",     (140, 255, 100)),
    ("Water",               (52, 125, 220)),
    ("Lava",                (230, 70, 25)),
    ("Honey",               (225, 155, 45)),
    ("Shimmer",             (160, 80, 225)),
    ("Snow / Ice",          (225, 240, 250)),
    ("Cloud / Sky Island",  (250, 250, 255)),
]


# ============================================================
# COLOR HELPERS
# ============================================================

def fallback_tile_color(tile_id, wall=False):
    """Neutral fallback — تولید رنگ اشتباه نکن."""

    if wall:
        # فقط تیره‌سازی، بدون پترن‌های عجیب
        return (95, 80, 70)

    # رنگ‌های خنثی بر اساس شناسه — ملایم
    neutral = [
        (120, 120, 120),
        (140, 110, 85),
        (110, 140, 85),
        (165, 145, 95),
        (120, 100, 85),
        (95, 120, 145),
        (140, 85, 85),
        (105, 85, 125),
        (85, 125, 95),
        (150, 115, 75),
        (120, 120, 130),
        (150, 145, 130),
    ]

    return neutral[tile_id % 12]


def base_tile_color(tile_id):
    return TILE_COLORS.get(
        tile_id,
        fallback_tile_color(tile_id, False),
    )


def base_wall_color(wall_id):
    return WALL_COLORS.get(
        wall_id,
        fallback_tile_color(wall_id, True),
    )


def apply_maphelper_paint(base, paint_id, is_wall):
    """Approximate MapHelper paint (corrected)."""

    if paint_id == 0 or paint_id == 31:
        return base

    # ---------- Deep paints: کامل جایگزین ----------
    if 25 <= paint_id <= 28:
        return PAINT_COLORS.get(paint_id, base)

    # ---------- Shadow ----------
    if paint_id == 29:
        return (
            int(base[0] * 0.3),
            int(base[1] * 0.3),
            int(base[2] * 0.3),
        )

    # ---------- Negative ----------
    if paint_id == 30:
        if is_wall:
            return (
                int((255 - base[0]) * 0.5),
                int((255 - base[1]) * 0.5),
                int((255 - base[2]) * 0.5),
            )
        return (
            255 - base[0],
            255 - base[1],
            255 - base[2],
        )

    # ---------- Normal paint (multiply) ----------
    paint = PAINT_COLORS.get(paint_id, (255, 255, 255))

    maximum = max(base)
    pr, pg, pb = paint

    return (
        int(pr * maximum / 255),
        int(pg * maximum / 255),
        int(pb * maximum / 255),
    )


def get_liquid_color(liquid_type):
    """Return pure liquid color (before blending)."""

    return LIQUID_COLORS.get(liquid_type)


def background_color(y, surface, rock_layer, height):
    """Approximate Terraria background (smooth gradient)."""

    if surface <= 0:
        surface = int(height * 0.30)

    if rock_layer <= surface:
        rock_layer = surface + int(height * 0.20)

    # ---------- Sky ----------
    if y < surface:
        ratio = y / max(1, surface)

        top    = (85, 170, 235)
        bottom = (150, 210, 240)

        return tuple(
            int(
                top[i]
                + (bottom[i] - top[i]) * ratio
            )
            for i in range(3)
        )

    # ---------- Dirt ----------
    if y < rock_layer:
        depth = (
            (y - surface)
            / max(1, rock_layer - surface)
        )

        return (
            int(151 - depth * 20),
            int(107 - depth * 15),
            int(75  - depth * 10),
        )

    # ---------- Stone / deeper ----------
    depth = (
        (y - rock_layer)
        / max(1, height - rock_layer)
    )

    v = max(45, int(115 - depth * 55))

    return (
        v,
        v,
        max(50, int(120 - depth * 45)),
    )


def pixel_color(
    tile_id,
    wall_id,
    liquid_type,
    liquid_amount,
    tile_paint,
    wall_paint,
    meta,
    y,
    surface,
    rock_layer,
    height,
):
    """
    Render one map pixel.

    ترتیب درست Terraria:
        background -> wall -> tile -> paint -> liquid(blend) -> highlight
    """

    has_tile = (tile_id != 0) and not (meta & 0x40)  # invisible_block
    is_inactive = bool(meta & 0x20)                  # actuated
    has_wall = (wall_id != 0) and not (meta & 0x80)  # invisible_wall

    bg = background_color(y, surface, rock_layer, height)

    color = bg

    # ---------- Wall ----------
    if has_wall:
        color = base_wall_color(wall_id)
        color = apply_maphelper_paint(color, wall_paint, True)

        color = (
            int(color[0] * 0.82),
            int(color[1] * 0.82),
            int(color[2] * 0.82),
        )

    # ---------- Tile ----------
    if has_tile and not is_inactive:
        color = base_tile_color(tile_id)
        color = apply_maphelper_paint(color, tile_paint, False)

        brick = meta & 0x07
        if brick:
            f = 0.92 if brick == 1 else 0.86
            color = (
                int(color[0] * f),
                int(color[1] * f),
                int(color[2] * f),
            )

    elif has_tile and is_inactive:
        # Actuated block: نیمه‌شفاف روی وال/پس‌زمینه
        tc = base_tile_color(tile_id)
        tc = apply_maphelper_paint(tc, tile_paint, False)

        color = (
            int(color[0] * 0.5 + tc[0] * 0.5),
            int(color[1] * 0.5 + tc[1] * 0.5),
            int(color[2] * 0.5 + tc[2] * 0.5),
        )

    # ---------- Liquid (blend) ----------
    if liquid_type and liquid_amount > 0:
        lc = get_liquid_color(liquid_type)

        if lc is not None:
            # شدت شفافیت بر اساس مقدار مایع
            strength = 0.35 + 0.55 * (liquid_amount / 255.0)

            color = (
                int(color[0] * (1 - strength) + lc[0] * strength),
                int(color[1] * (1 - strength) + lc[1] * strength),
                int(color[2] * (1 - strength) + lc[2] * strength),
            )

    # ---------- Highlight ----------
    if has_tile:
        hl = HIGHLIGHT_TILES.get(tile_id)

        if hl is not None:
            # ترکیب 70% رنگ highlight + 30% رنگ اصلی
            color = (
                int(hl[0] * 0.7 + color[0] * 0.3),
                int(hl[1] * 0.7 + color[1] * 0.3),
                int(hl[2] * 0.7 + color[2] * 0.3),
            )

    return color


# ============================================================
# LEGEND WRITER
# ============================================================

def write_legend():
    """Write a small legend next to the PNG."""

    try:
        with open(LEGEND_FILE, "w", encoding="utf-8") as f:
            f.write("Terraria Map Legend\n")
            f.write("=" * 40 + "\n\n")

            for name, (r, g, b) in LEGEND_ENTRIES:
                f.write(
                    f"  {name:<22} RGB=({r:>3},{g:>3},{b:>3})  "
                    f"#{r:02X}{g:02X}{b:02X}\n"
                )

            f.write("\n")
            f.write("Highlighted special tiles:\n")

            for tile_id, color in HIGHLIGHT_TILES.items():
                r, g, b = color
                f.write(
                    f"  tile_id={tile_id:<5} RGB=({r:>3},{g:>3},{b:>3})\n"
                )

        print(f"[+] Legend saved: {LEGEND_FILE.resolve()}")

    except Exception as exc:
        print(f"[!] Legend write error: {exc}")


# ============================================================
# PNG RENDERER
# ============================================================

def create_png(world, info):
    """Render mmap world to PNG."""

    width = world.width
    height = world.height

    surface = info.get("surface", int(height * 0.30))
    rock_layer = info.get("rock_layer", int(height * 0.50))

    print()
    print("[*] Rendering PNG...")
    print(f"[*] Resolution: {width}x{height}")

    image = Image.new("RGB", (width, height))

    strip_height = 16

    tiles_map = world.maps["tiles"]
    walls_map = world.maps["walls"]
    liquids_map = world.maps["liquids"]
    paint_map = world.maps["paint"]
    metadata_map = world.maps["metadata"]

    for y0 in range(0, height, strip_height):

        current_height = min(strip_height, height - y0)

        pixels = bytearray(width * current_height * 3)

        for sy in range(current_height):

            y = y0 + sy
            row_index = y * width

            for x in range(width):

                index = row_index + x
                offset = index * 2

                tile_id = (
                    tiles_map[offset]
                    | (tiles_map[offset + 1] << 8)
                )

                wall_id = (
                    walls_map[offset]
                    | (walls_map[offset + 1] << 8)
                )

                liquid_value = (
                    liquids_map[offset]
                    | (liquids_map[offset + 1] << 8)
                )

                liquid_amount = liquid_value & 0xFF
                liquid_type = liquid_value >> 8

                paint_value = (
                    paint_map[offset]
                    | (paint_map[offset + 1] << 8)
                )

                tile_paint = paint_value & 0xFF
                wall_paint = paint_value >> 8

                meta = metadata_map[index]

                r, g, b = pixel_color(
                    tile_id,
                    wall_id,
                    liquid_type,
                    liquid_amount,
                    tile_paint,
                    wall_paint,
                    meta,
                    y,
                    surface,
                    rock_layer,
                    height,
                )

                pixel_index = ((sy * width + x) * 3)

                pixels[pixel_index] = r
                pixels[pixel_index + 1] = g
                pixels[pixel_index + 2] = b

        strip = Image.frombytes(
            "RGB",
            (width, current_height),
            bytes(pixels),
        )

        image.paste(strip, (0, y0))
        strip.close()
        del pixels

        rendered = y0 + current_height

        if y0 % 160 == 0 or rendered >= height:
            print(f"[*] Rendered {rendered}/{height}")

    print()
    print("[*] Saving PNG...")

    image.save(PNG_FILE, "PNG", optimize=False)
    image.close()

    print(f"[+] PNG saved: {PNG_FILE.resolve()}")


# ============================================================
# SCANNER
# ============================================================

async def scanner(writer, state):
    """Scan the world ONLY after Packet 49."""

    print()
    print("[*] Scanner waiting for Connection Complete...")

    try:
        await asyncio.wait_for(
            state.connection_complete.wait(),
            timeout=30,
        )
    except asyncio.TimeoutError:
        print("[!] Packet 49 was not received within 30 seconds.")
        return

    if not state.running:
        return

    await asyncio.sleep(1.0)

    world = state.world_map

    if world is None:
        print("[!] No world storage.")
        return

    columns = world.section_columns
    rows = world.section_rows
    total = columns * rows

    print()
    print("[*] Section grid:")
    print(f"    {columns} x {rows}")
    print(f"    Total: {total}")
    print()
    print("[*] Starting world scan...")

    move = 0

    spawn_x = state.world_info["spawn_x"]
    spawn_y = state.world_info["spawn_y"]

    print(f"[>] Moving to spawn {spawn_x},{spawn_y}")

    await send_update_player(
        writer,
        state.player_id,
        spawn_x,
        spawn_y,
    )

    move += 1
    await asyncio.sleep(MOVE_DELAY)

    for sy in range(rows):

        if not state.running:
            break

        if sy % 2 == 0:
            x_range = range(columns)
        else:
            x_range = range(columns - 1, -1, -1)

        for sx in x_range:

            if not state.running:
                break

            x = sx * SECTION_WIDTH + SECTION_WIDTH // 2
            y = sy * SECTION_HEIGHT + SECTION_HEIGHT // 2

            x = min(x, world.width - 1)
            y = min(y, world.height - 1)

            await send_update_player(
                writer,
                state.player_id,
                x,
                y,
            )

            move += 1

            print(
                f"[>] Move {move} -> {x},{y} "
                f"| sections={len(world.sections)}"
            )

            await asyncio.sleep(MOVE_DELAY)

    print()
    print("[+] Scan path finished.")


# ============================================================
# STATE
# ============================================================

class State:

    def __init__(self):
        self.player_id = None
        self.world_map = None
        self.world_info = None
        self.world_info_received = False
        self.spawn_sent = False
        self.connection_complete = asyncio.Event()
        self.running = True
        self.packet10_count = 0
        self.decode_errors = 0
        self.server_disconnect = False


# ============================================================
# RECEIVER
# ============================================================

async def receiver(reader, writer, state):
    """Receive server packets."""

    try:
        while state.running:

            packet_id, payload = await read_packet(reader)

            # ---------- Disconnect ----------
            if packet_id == 2:

                state.server_disconnect = True

                print()
                print("[!] Server disconnected.")
                print("    Payload:", payload.hex(" "))

                try:
                    reason, _ = read_string(payload, 0)
                    print("    String:", repr(reason))
                except Exception as exc:
                    print(f"    NetworkText decode failed: {exc}")

                state.running = False
                break

            # ---------- Set User Slot ----------
            if packet_id == 3:

                if not payload:
                    continue

                state.player_id = payload[0]

                print(f"[+] Player ID: {state.player_id}")

                await send_player_info(writer, state.player_id)
                await send_inventory(writer, state.player_id)
                await request_world(writer)

                continue

            # ---------- World Info ----------
            if packet_id == 7:

                try:
                    info = parse_world_info(payload)
                except Exception as exc:
                    print(f"[!] WorldInfo parse error: {exc}")
                    continue

                state.world_info = info

                print()
                print("========== WORLD ==========")
                print(f"Name:      {info['name']}")
                print(f"Size:      {info['width']} x {info['height']}")
                print(f"Spawn:     {info['spawn_x']}, {info['spawn_y']}")
                print(f"Surface:   {info['surface']}")
                print(f"Rock:      {info['rock_layer']}")
                print(f"World ID:  {info['world_id']}")
                print(f"Game Mode: {info['game_mode']}")
                print("============================")

                if not state.world_info_received:

                    state.world_info_received = True

                    state.world_map = WorldMap(
                        info["width"],
                        info["height"],
                    )

                    await request_essential_tiles(
                        writer,
                        info["spawn_x"],
                        info["spawn_y"],
                    )

                continue

            # ---------- Packet 10 ----------
            if packet_id == 10:

                state.packet10_count += 1

                try:
                    (
                        start_x,
                        start_y,
                        width,
                        height,
                        tiles,
                    ) = parse_section(payload)

                    if state.world_map is None:
                        continue

                    added = state.world_map.add_section(
                        start_x,
                        start_y,
                        width,
                        height,
                        tiles,
                    )

                    if not added:
                        continue

                    number = len(state.world_map.sections)

                    print(
                        f"[+] Section {number}: "
                        f"{start_x},{start_y} {width}x{height}"
                    )

                    if not state.spawn_sent:

                        state.spawn_sent = True

                        await send_spawn_player(
                            writer,
                            state.player_id,
                            state.world_info["spawn_x"],
                            state.world_info["spawn_y"],
                        )

                        print("[>] Spawn packet sent")

                except Exception as exc:

                    state.decode_errors += 1
                    print(f"[!] Packet 10 decode error: {exc}")

                continue

            # ---------- Connection Complete ----------
            if packet_id == 49:

                print()
                print("[+] Connection complete")

                state.connection_complete.set()
                continue

            # ---------- Ignore others ----------
            if packet_id in (9, 12, 14):
                continue

    except asyncio.IncompleteReadError:
        print("[!] Connection closed by server.")

    except asyncio.CancelledError:
        pass

    except Exception as exc:
        print("[!] Receiver error:")
        print(f"    {type(exc).__name__}: {exc}")

    finally:
        state.running = False


# ============================================================
# MAIN
# ============================================================

async def main():
    """Main program."""

    state = State()

    print("==========================================")
    print(" Terraria 1.4.5.x World Map Downloader")
    print("==========================================")
    print(f"[*] Connecting to {HOST}:{PORT}")

    try:
        reader, writer = await asyncio.open_connection(HOST, PORT)
    except Exception as exc:
        print("[!] Connection failed:")
        print(f"    {repr(exc)}")
        return

    print("[+] Connected")

    receiver_task = None
    scanner_task = None

    try:
        # ---------- Packet 1 ----------
        await send_packet(
            writer,
            1,
            write_string(VERSION),
        )

        print(f"[>] Version sent: {VERSION}")

        # ---------- Start receiver ----------
        receiver_task = asyncio.create_task(
            receiver(reader, writer, state)
        )

        # ---------- Wait until WorldInfo ----------
        while (
            state.world_map is None
            and state.running
            and not receiver_task.done()
        ):
            await asyncio.sleep(0.1)

        if state.world_map is None:
            print("[!] World was not received.")
            return

        # ---------- Start scanner ----------
        if SCAN_WHOLE_WORLD:

            scanner_task = asyncio.create_task(
                scanner(writer, state)
            )

            while (
                not scanner_task.done()
                and state.running
            ):
                await asyncio.sleep(0.2)

            if scanner_task and scanner_task.done():
                try:
                    await scanner_task
                except Exception as exc:
                    print("[!] Scanner error:", repr(exc))

        # ---------- Wait for final sections ----------
        await asyncio.sleep(2.0)

    except KeyboardInterrupt:
        print("\n[!] Stopped by user.")

    except Exception as exc:
        print()
        print("[!] ERROR:")
        print(f"    {type(exc).__name__}: {exc}")

    finally:

        state.running = False

        if scanner_task and not scanner_task.done():
            scanner_task.cancel()
            try:
                await scanner_task
            except asyncio.CancelledError:
                pass

        if receiver_task and not receiver_task.done():
            receiver_task.cancel()
            try:
                await receiver_task
            except asyncio.CancelledError:
                pass

        # ---------- Results ----------
        print()
        print("==========================================")
        print("[+] RESULT")
        print("==========================================")
        print(f"Packet 10 received: {state.packet10_count}")
        print(f"Packet 10 errors:   {state.decode_errors}")

        if state.world_map is not None:

            world = state.world_map

            try:
                world.flush()
            except Exception:
                pass

            expected = (
                world.section_columns
                * world.section_rows
            )

            print(f"Sections received: {len(world.sections)}")
            print(f"Sections expected: {expected}")

            if len(world.sections) > 0:
                try:
                    create_png(world, state.world_info)
                    write_legend()
                except Exception as exc:
                    print("[!] PNG error:")
                    print(f"    {type(exc).__name__}: {exc}")

        if state.world_map is not None:
            try:
                state.world_map.close()
            except Exception as exc:
                print("[!] Storage close error:", repr(exc))

        try:
            writer.close()
            await writer.wait_closed()
        except Exception:
            pass

        print()
        print("[*] Finished.")


# ============================================================
# RUN
# ============================================================

if __name__ == "__main__":
    asyncio.run(main())
