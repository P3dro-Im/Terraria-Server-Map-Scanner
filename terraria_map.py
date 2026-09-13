import asyncio
import mmap
import struct
import zlib
from pathlib import Path

from PIL import Image


# ============================================================
# CONFIG
# ============================================================

HOST = "IP or DOMAIN"
PORT = 7777

VERSION = "Terraria319"
PLAYER_NAME = "Bot"

WORLD_DIR = Path("terraria_world")

TILES_FILE = WORLD_DIR / "tiles.bin"
WALLS_FILE = WORLD_DIR / "walls.bin"
LIQUIDS_FILE = WORLD_DIR / "liquids.bin"
PAINT_FILE = WORLD_DIR / "paint.bin"
META_FILE = WORLD_DIR / "metadata.bin"
FRAMES_FILE = WORLD_DIR / "frames.bin"

PNG_FILE = Path("terraria_map.png")

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

    # Player ID
    payload.append(player_id)

    # Skin variant
    payload.append(0)

    # Voice variant
    payload.append(1)

    # Voice pitch
    payload.extend(
        struct.pack(
            "<f",
            0.0,
        )
    )

    # Hair
    payload.append(0)

    # Name
    payload.extend(
        write_string(
            PLAYER_NAME
        )
    )

    # Hair dye
    payload.append(0)

    # Accessory visibility
    payload.extend(
        struct.pack(
            "<H",
            0,
        )
    )

    # Hide misc
    payload.append(0)

    # Hair
    payload.extend(
        (120, 80, 60)
    )

    # Skin
    payload.extend(
        (255, 200, 170)
    )

    # Eyes
    payload.extend(
        (0, 0, 0)
    )

    # Shirt
    payload.extend(
        (100, 100, 100)
    )

    # Undershirt
    payload.extend(
        (150, 150, 150)
    )

    # Pants
    payload.extend(
        (50, 50, 50)
    )

    # Shoes
    payload.extend(
        (40, 40, 40)
    )

    # Difficulty
    payload.append(0)

    # Additional flags
    payload.append(0)

    # Additional flags
    payload.append(0)

    await send_packet(
        writer,
        4,
        bytes(payload),
    )

    print("[>] PlayerInfo sent")


async def send_inventory(
    writer,
    player_id,
):
    """Send 59 empty inventory slots."""

    for slot in range(59):

        payload = bytearray()

        payload.append(
            player_id
        )

        payload.extend(
            struct.pack(
                "<h",
                slot,
            )
        )

        payload.extend(
            struct.pack(
                "<h",
                0,
            )
        )

        payload.append(0)

        payload.extend(
            struct.pack(
                "<h",
                0,
            )
        )

        payload.append(0)

        await send_packet(
            writer,
            5,
            bytes(payload),
        )

    print("[>] Inventory sent")


async def request_world(
    writer,
):
    """Request WorldInfo."""

    await send_packet(
        writer,
        6,
    )

    print("[>] WorldInfo requested")


async def request_essential_tiles(
    writer,
    x,
    y,
):
    """
    Request initial world section around
    the actual spawn position.
    """

    await send_packet(
        writer,
        8,
        struct.pack(
            "<ii",
            int(x),
            int(y),
        ),
    )

    print(
        "[>] Initial tile request sent"
    )


async def send_spawn_player(
    writer,
    player_id,
    x,
    y,
):
    """Send Packet 12."""

    payload = bytearray()

    payload.append(player_id)

    payload.extend(
        struct.pack(
            "<h",
            int(x),
        )
    )

    payload.extend(
        struct.pack(
            "<h",
            int(y),
        )
    )

    # PVE deaths
    payload.extend(
        struct.pack(
            "<h",
            0,
        )
    )

    # PVP deaths
    payload.extend(
        struct.pack(
            "<h",
            0,
        )
    )

    # Respawn time
    payload.extend(
        struct.pack(
            "<i",
            0,
        )
    )

    # SpawningIntoWorld
    payload.append(1)

    await send_packet(
        writer,
        12,
        bytes(payload),
    )


async def send_update_player(
    writer,
    player_id,
    tile_x,
    tile_y,
):
    """Send Packet 13 using tile coordinates."""

    payload = bytearray()

    payload.append(player_id)

    # Control
    payload.append(0)

    # Pulley
    payload.append(0)

    # Misc
    payload.append(0)

    # Sleeping
    payload.append(0)

    # Selected item
    payload.append(0)

    # Terraria position is pixels.
    payload.extend(
        struct.pack(
            "<ff",
            float(tile_x * 16),
            float(tile_y * 16),
        )
    )

    await send_packet(
        writer,
        13,
        bytes(payload),
    )


# ============================================================
# WORLD STORAGE
# ============================================================

class WorldMap:
    """Disk-backed Terraria world."""

    def __init__(
        self,
        width,
        height,
    ):
        self.width = width
        self.height = height

        self.total_tiles = (
            width * height
        )

        self.section_columns = (
            width
            + SECTION_WIDTH
            - 1
        ) // SECTION_WIDTH

        self.section_rows = (
            height
            + SECTION_HEIGHT
            - 1
        ) // SECTION_HEIGHT

        self.sections = set()

        WORLD_DIR.mkdir(
            parents=True,
            exist_ok=True,
        )

        print()
        print(
            "[*] Creating world storage"
        )

        print(
            f"[*] Size: "
            f"{width} x {height}"
        )

        print(
            f"[*] Tiles: "
            f"{self.total_tiles:,}"
        )

        self.files = {}
        self.maps = {}

        specs = {
            "tiles": (
                TILES_FILE,
                2,
            ),
            "walls": (
                WALLS_FILE,
                2,
            ),
            "liquids": (
                LIQUIDS_FILE,
                2,
            ),
            "paint": (
                PAINT_FILE,
                2,
            ),
            "metadata": (
                META_FILE,
                1,
            ),
            "frames": (
                FRAMES_FILE,
                4,
            ),
        }

        for name, (
            path,
            bytes_per_tile,
        ) in specs.items():

            size = (
                self.total_tiles
                * bytes_per_tile
            )

            file = open(
                path,
                "w+b",
            )

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

        key = (
            start_x,
            start_y,
        )

        if key in self.sections:
            return False

        if start_x < 0 or start_y < 0:
            return False

        if start_x >= self.width:
            return False

        if start_y >= self.height:
            return False

        width = min(
            width,
            self.width - start_x,
        )

        height = min(
            height,
            self.height - start_y,
        )

        if len(tiles) < width * height:
            return False

        tiles_map = self.maps["tiles"]
        walls_map = self.maps["walls"]
        liquids_map = self.maps["liquids"]
        paint_map = self.maps["paint"]
        meta_map = self.maps["metadata"]
        frames_map = self.maps["frames"]

        for row in range(height):

            section_row = (
                row * width
            )

            world_row = (
                (start_y + row)
                * self.width
                + start_x
            )

            for col in range(width):

                tile = tiles[
                    section_row + col
                ]

                world_index = (
                    world_row + col
                )

                offset = (
                    world_index * 2
                )

                # Tile
                struct.pack_into(
                    "<H",
                    tiles_map,
                    offset,
                    tile["tile_id"],
                )

                # Wall
                struct.pack_into(
                    "<H",
                    walls_map,
                    offset,
                    tile["wall_id"],
                )

                # Liquid
                liquid_value = (
                    tile["liquid_amount"]
                    | (
                        tile["liquid_type"]
                        << 8
                    )
                )

                struct.pack_into(
                    "<H",
                    liquids_map,
                    offset,
                    liquid_value,
                )

                # Paint
                paint_value = (
                    tile["tile_paint"]
                    | (
                        tile["wall_paint"]
                        << 8
                    )
                )

                struct.pack_into(
                    "<H",
                    paint_map,
                    offset,
                    paint_value,
                )

                # Metadata
                meta = (
                    tile["brick_style"]
                    & 0x07
                )

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

                meta_map[
                    world_index
                ] = meta

                # Frame
                frame_value = (
                    (
                        tile["frame_x"]
                        & 0xFFFF
                    )
                    | (
                        (
                            tile["frame_y"]
                            & 0xFFFF
                        )
                        << 16
                    )
                )

                struct.pack_into(
                    "<I",
                    frames_map,
                    world_index * 4,
                    frame_value,
                )

        self.sections.add(key)

        if len(self.sections) % 5 == 0:
            self.flush()

        return True

    def flush(self):
        """Flush mmap files."""

        for mapping in self.maps.values():
            mapping.flush()

    def close(self):
        """Close all files."""

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

def decode_tile(
    data,
    pos,
):
    """Decode one Terraria tile."""

    if pos >= len(data):
        raise ValueError(
            "Tile data ended early"
        )

    flags1 = data[pos]
    pos += 1

    flags2 = 0
    flags3 = 0
    flags4 = 0

    # Header 2
    if flags1 & 0x01:

        if pos >= len(data):
            raise ValueError(
                "Missing header 2"
            )

        flags2 = data[pos]
        pos += 1

        # Header 3
        if flags2 & 0x01:

            if pos >= len(data):
                raise ValueError(
                    "Missing header 3"
                )

            flags3 = data[pos]
            pos += 1

            # Header 4
            if flags3 & 0x01:

                if pos >= len(data):
                    raise ValueError(
                        "Missing header 4"
                    )

                flags4 = data[pos]
                pos += 1

    active = bool(
        flags1 & 0x02
    )

    tile_id = 0

    frame_x = 0
    frame_y = 0

    # --------------------------------------------------------
    # Tile
    # --------------------------------------------------------

    if active:

        if pos >= len(data):
            raise ValueError(
                "Missing tile ID"
            )

        tile_id = data[pos]
        pos += 1

        if flags1 & 0x20:

            if pos >= len(data):
                raise ValueError(
                    "Missing tile ID high byte"
                )

            tile_id |= (
                data[pos]
                << 8
            )

            pos += 1

        if frame_important(tile_id):

            if pos + 4 > len(data):
                raise ValueError(
                    "Missing tile frame"
                )

            frame_x = struct.unpack_from(
                "<h",
                data,
                pos,
            )[0]

            pos += 2

            frame_y = struct.unpack_from(
                "<h",
                data,
                pos,
            )[0]

            pos += 2

    # --------------------------------------------------------
    # Wall
    # --------------------------------------------------------

    wall_id = 0

    if flags1 & 0x04:

        if pos >= len(data):
            raise ValueError(
                "Missing wall ID"
            )

        wall_id = data[pos]
        pos += 1

        if flags3 & 0x40:

            if pos >= len(data):
                raise ValueError(
                    "Missing wall high byte"
                )

            wall_id |= (
                data[pos]
                << 8
            )

            pos += 1

    # --------------------------------------------------------
    # Liquid
    # --------------------------------------------------------

    liquid_amount = 0
    liquid_type = 0

    liquid_bits = (
        flags1 & 0x18
    )

    if liquid_bits:

        if pos >= len(data):
            raise ValueError(
                "Missing liquid amount"
            )

        if liquid_bits == 0x08:

            # Water
            liquid_type = 1

            # Shimmer
            if flags3 & 0x80:
                liquid_type = 4

        elif liquid_bits == 0x10:

            # Lava
            liquid_type = 2

        elif liquid_bits == 0x18:

            # Honey
            liquid_type = 3

        liquid_amount = data[pos]
        pos += 1

    # --------------------------------------------------------
    # Paint
    # --------------------------------------------------------

    tile_paint = 0
    wall_paint = 0

    if flags3 & 0x08:

        if pos >= len(data):
            raise ValueError(
                "Missing tile paint"
            )

        tile_paint = data[pos]
        pos += 1

    if flags3 & 0x10:

        if pos >= len(data):
            raise ValueError(
                "Missing wall paint"
            )

        wall_paint = data[pos]
        pos += 1

    # --------------------------------------------------------
    # Brick style
    # --------------------------------------------------------

    brick_style = (
        (flags2 >> 4)
        & 0x07
    )

    half_block = (
        brick_style == 1
    )

    # --------------------------------------------------------
    # Other flags
    # --------------------------------------------------------

    actuator = bool(
        flags3 & 0x02
    )

    inactive = bool(
        flags3 & 0x04
    )

    invisible_block = bool(
        flags4 & 0x02
    )

    invisible_wall = bool(
        flags4 & 0x04
    )

    fullbright_block = bool(
        flags4 & 0x08
    )

    fullbright_wall = bool(
        flags4 & 0x10
    )

    # --------------------------------------------------------
    # RLE
    # --------------------------------------------------------

    run = 0

    if flags1 & 0x40:

        if pos >= len(data):
            raise ValueError(
                "Missing RLE byte"
            )

        run = data[pos]
        pos += 1

    elif flags1 & 0x80:

        if pos + 2 > len(data):
            raise ValueError(
                "Missing RLE ushort"
            )

        run = struct.unpack_from(
            "<H",
            data,
            pos,
        )[0]

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
        data = zlib.decompress(
            payload,
            -zlib.MAX_WBITS,
        )
    except zlib.error:
        data = zlib.decompress(payload)

    if len(data) < 12:
        raise ValueError(
            "Section payload too short"
        )

    pos = 0

    start_x = struct.unpack_from(
        "<i",
        data,
        pos,
    )[0]
    pos += 4

    start_y = struct.unpack_from(
        "<i",
        data,
        pos,
    )[0]
    pos += 4

    width = struct.unpack_from(
        "<h",
        data,
        pos,
    )[0]
    pos += 2

    height = struct.unpack_from(
        "<h",
        data,
        pos,
    )[0]
    pos += 2

    if width <= 0 or height <= 0:
        raise ValueError(
            f"Invalid section size "
            f"{width}x{height}"
        )

    if width > SECTION_WIDTH:
        raise ValueError(
            f"Section width too large: "
            f"{width}"
        )

    if height > SECTION_HEIGHT:
        raise ValueError(
            f"Section height too large: "
            f"{height}"
        )

    total = width * height

    tiles = []
    append_tile = tiles.append

    while len(tiles) < total:

        tile, run, pos = decode_tile(
            data,
            pos,
        )

        count = min(
            run + 1,
            total - len(tiles),
        )

        for _ in range(count):
            append_tile(tile)

    return (
        start_x,
        start_y,
        width,
        height,
        tiles,
    )


# ============================================================
# WORLD INFO
# ============================================================

def parse_world_info(payload):
    """Parse the WorldInfo packet."""

    pos = 0

    if len(payload) < 24:
        raise ValueError(
            "WorldInfo packet too short"
        )

    # World time
    pos += 4

    # Day flags
    pos += 1

    # Moon phase
    pos += 1

    width = struct.unpack_from(
        "<h",
        payload,
        pos,
    )[0]
    pos += 2

    height = struct.unpack_from(
        "<h",
        payload,
        pos,
    )[0]
    pos += 2

    spawn_x = struct.unpack_from(
        "<h",
        payload,
        pos,
    )[0]
    pos += 2

    spawn_y = struct.unpack_from(
        "<h",
        payload,
        pos,
    )[0]
    pos += 2

    surface = struct.unpack_from(
        "<h",
        payload,
        pos,
    )[0]
    pos += 2

    rock_layer = struct.unpack_from(
        "<h",
        payload,
        pos,
    )[0]
    pos += 2

    world_id = struct.unpack_from(
        "<i",
        payload,
        pos,
    )[0]
    pos += 4

    name, pos = read_string(
        payload,
        pos,
    )

    if pos >= len(payload):
        raise ValueError(
            "Missing game mode"
        )

    game_mode = payload[pos]
    pos += 1

    world_uuid = b""

    if pos + 16 <= len(payload):
        world_uuid = payload[
            pos:pos + 16
        ]
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
# COLORS
# ============================================================

TILE_COLORS = {
    0: (151, 107, 75),
    1: (128, 128, 128),
    2: (63, 150, 63),
    3: (76, 175, 76),
    4: (151, 107, 75),
    5: (139, 96, 62),

    6: (120, 120, 120),
    7: (184, 115, 51),
    8: (218, 165, 55),
    9: (155, 155, 170),

    23: (103, 78, 125),
    24: (83, 145, 67),
    25: (112, 80, 130),

    30: (151, 107, 75),
    31: (126, 84, 52),

    37: (76, 76, 82),
    38: (91, 91, 96),

    53: (218, 198, 134),

    57: (134, 61, 43),
    58: (107, 77, 56),

    59: (78, 145, 67),
    60: (69, 132, 61),

    69: (100, 63, 117),
    70: (112, 68, 130),

    75: (141, 83, 55),
    76: (112, 66, 49),

    109: (188, 111, 190),
    110: (168, 94, 180),
    112: (115, 55, 135),

    116: (205, 205, 220),

    147: (190, 220, 235),
    161: (167, 215, 235),

    199: (155, 48, 53),
    200: (170, 56, 60),
    203: (145, 45, 48),
    204: (125, 38, 42),
}


WALL_COLORS = {
    1: (105, 80, 60),
    2: (95, 95, 95),
    3: (75, 65, 55),
    4: (105, 75, 50),
    5: (80, 80, 85),
    7: (90, 55, 90),
    8: (75, 50, 85),
    9: (70, 70, 75),
    10: (115, 85, 60),
    15: (85, 60, 45),
    16: (70, 55, 45),
    21: (120, 105, 75),
    23: (90, 60, 100),
    24: (95, 50, 105),
}


PAINT_COLORS = {
    0: (255, 255, 255),

    1: (255, 0, 0),
    2: (255, 127, 0),
    3: (255, 255, 0),
    4: (127, 255, 0),
    5: (0, 255, 0),
    6: (0, 255, 127),
    7: (0, 255, 255),
    8: (0, 127, 255),
    9: (0, 0, 255),
    10: (127, 0, 255),
    11: (191, 0, 255),
    12: (255, 0, 127),

    13: (127, 0, 0),
    14: (127, 63, 0),
    15: (127, 127, 0),
    16: (63, 127, 0),
    17: (0, 127, 0),
    18: (0, 127, 63),
    19: (0, 127, 127),
    20: (0, 63, 127),
    21: (0, 0, 127),
    22: (63, 0, 127),
    23: (95, 0, 127),
    24: (127, 0, 63),

    25: (0, 0, 0),
    26: (255, 255, 255),
    27: (128, 128, 128),
    28: (127, 63, 31),

    29: (0, 0, 0),
    30: (255, 255, 255),
    31: (255, 255, 255),
}


LIQUID_COLORS = {
    1: (52, 125, 220),
    2: (230, 70, 25),
    3: (225, 155, 45),
    4: (160, 80, 225),
}


def fallback_tile_color(
    tile_id,
    wall=False,
):
    """Generate a conservative fallback color."""

    if wall:

        value = (
            tile_id * 37
        ) % 80

        base = 55 + value

        return (
            base,
            max(45, base - 10),
            max(40, base - 20),
        )

    colors = (
        (125, 125, 125),
        (145, 105, 75),
        (105, 145, 75),
        (170, 145, 85),
        (115, 90, 70),
        (90, 120, 150),
        (145, 75, 75),
        (100, 75, 130),
        (80, 130, 90),
        (155, 110, 65),
        (115, 115, 125),
        (155, 145, 125),
    )

    return colors[tile_id % 12]


def base_tile_color(tile_id):
    return TILE_COLORS.get(
        tile_id,
        fallback_tile_color(
            tile_id,
            False,
        ),
    )


def base_wall_color(wall_id):
    return WALL_COLORS.get(
        wall_id,
        fallback_tile_color(
            wall_id,
            True,
        ),
    )


def apply_maphelper_paint(
    base,
    paint_id,
    is_wall,
):
    """Approximate MapHelper paint."""

    if paint_id == 0:
        return base

    paint = PAINT_COLORS.get(
        paint_id,
        (255, 255, 255),
    )

    r, g, b = base
    pr, pg, pb = paint

    if paint_id == 31:
        return base

    if paint_id == 29:

        factor = 0.3

        return (
            int(r * factor),
            int(g * factor),
            int(b * factor),
        )

    if paint_id == 30:

        if is_wall:

            return (
                int((255 - r) * 0.5),
                int((255 - g) * 0.5),
                int((255 - b) * 0.5),
            )

        return (
            255 - r,
            255 - g,
            255 - b,
        )

    maximum = max(
        r,
        g,
        b,
    )

    return (
        int(pr * maximum / 255),
        int(pg * maximum / 255),
        int(pb * maximum / 255),
    )


def get_liquid_color(
    liquid_type,
    amount,
):
    """Return liquid color."""

    color = LIQUID_COLORS.get(
        liquid_type
    )

    if color is None:
        return None

    strength = (
        0.45
        + 0.55
        * (
            amount / 255.0
        )
    )

    return tuple(
        max(
            0,
            min(
                255,
                int(
                    12
                    + channel
                    * strength
                ),
            ),
        )
        for channel in color
    )


def background_color(
    y,
    surface,
    rock_layer,
    height,
):
    """Approximate Terraria background."""

    if surface <= 0:
        surface = int(
            height * 0.30
        )

    if rock_layer <= surface:
        rock_layer = (
            surface
            + int(height * 0.20)
        )

    if y < surface:

        ratio = (
            y
            / max(
                1,
                surface,
            )
        )

        top = (
            90,
            175,
            235,
        )

        bottom = (
            135,
            205,
            235,
        )

        return tuple(
            int(
                top[i]
                + (
                    bottom[i]
                    - top[i]
                )
                * ratio
            )
            for i in range(3)
        )

    if y < rock_layer:
        return (
            151,
            107,
            75,
        )

    depth = (
        y - rock_layer
    ) / max(
        1,
        height - rock_layer,
    )

    value = max(
        55,
        int(
            115
            - depth * 40
        ),
    )

    return (
        value,
        value,
        max(
            60,
            int(
                120
                - depth * 35
            ),
        ),
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
    """Render one map pixel."""

    liquid = get_liquid_color(
        liquid_type,
        liquid_amount,
    )

    if liquid is not None:
        return liquid

    # Active tile
    if tile_id != 0:

        if meta & 0x40:
            return background_color(
                y,
                surface,
                rock_layer,
                height,
            )

        color = base_tile_color(
            tile_id
        )

        color = apply_maphelper_paint(
            color,
            tile_paint,
            False,
        )

        if meta & 0x20:

            color = tuple(
                int(
                    channel * 0.55
                )
                for channel in color
            )

        brick_style = (
            meta & 0x07
        )

        if brick_style:

            factor = 0.90

            if brick_style >= 2:
                factor = 0.86

            color = tuple(
                int(
                    channel * factor
                )
                for channel in color
            )

        return color

    # Wall
    if wall_id != 0:

        if meta & 0x80:
            return background_color(
                y,
                surface,
                rock_layer,
                height,
            )

        color = base_wall_color(
            wall_id
        )

        color = apply_maphelper_paint(
            color,
            wall_paint,
            True,
        )

        return tuple(
            int(
                channel * 0.78
            )
            for channel in color
        )

    return background_color(
        y,
        surface,
        rock_layer,
        height,
    )


# ============================================================
# PNG RENDERER
# ============================================================

def create_png(world, info):
    """Render mmap world to PNG."""

    width = world.width
    height = world.height

    surface = info.get(
        "surface",
        int(height * 0.30),
    )

    rock_layer = info.get(
        "rock_layer",
        int(height * 0.50),
    )

    print()
    print("[*] Rendering PNG...")

    print(
        f"[*] Resolution: "
        f"{width}x{height}"
    )

    image = Image.new(
        "RGB",
        (
            width,
            height,
        ),
    )

    strip_height = 16

    tiles_map = world.maps["tiles"]
    walls_map = world.maps["walls"]
    liquids_map = world.maps["liquids"]
    paint_map = world.maps["paint"]
    metadata_map = world.maps["metadata"]

    for y0 in range(
        0,
        height,
        strip_height,
    ):

        current_height = min(
            strip_height,
            height - y0,
        )

        pixels = bytearray(
            width
            * current_height
            * 3
        )

        for sy in range(
            current_height
        ):

            y = y0 + sy

            row_index = (
                y * width
            )

            for x in range(width):

                index = (
                    row_index + x
                )

                offset = (
                    index * 2
                )

                tile_id = (
                    tiles_map[offset]
                    | (
                        tiles_map[
                            offset + 1
                        ]
                        << 8
                    )
                )

                wall_id = (
                    walls_map[offset]
                    | (
                        walls_map[
                            offset + 1
                        ]
                        << 8
                    )
                )

                liquid_value = (
                    liquids_map[offset]
                    | (
                        liquids_map[
                            offset + 1
                        ]
                        << 8
                    )
                )

                liquid_amount = (
                    liquid_value & 0xFF
                )

                liquid_type = (
                    liquid_value >> 8
                )

                paint_value = (
                    paint_map[offset]
                    | (
                        paint_map[
                            offset + 1
                        ]
                        << 8
                    )
                )

                tile_paint = (
                    paint_value & 0xFF
                )

                wall_paint = (
                    paint_value >> 8
                )

                meta = metadata_map[
                    index
                ]

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

                pixel_index = (
                    (
                        sy * width
                        + x
                    ) * 3
                )

                pixels[
                    pixel_index
                ] = r

                pixels[
                    pixel_index + 1
                ] = g

                pixels[
                    pixel_index + 2
                ] = b

        strip = Image.frombytes(
            "RGB",
            (
                width,
                current_height,
            ),
            bytes(pixels),
        )

        image.paste(
            strip,
            (
                0,
                y0,
            ),
        )

        strip.close()

        del pixels

        rendered = (
            y0
            + current_height
        )

        if (
            y0 % 160 == 0
            or rendered >= height
        ):

            print(
                f"[*] Rendered "
                f"{rendered}/{height}"
            )

    print()
    print("[*] Saving PNG...")

    image.save(
        PNG_FILE,
        "PNG",
        optimize=False,
    )

    image.close()

    print(
        f"[+] PNG saved: "
        f"{PNG_FILE.resolve()}"
    )


# ============================================================
# SCANNER
# ============================================================

async def scanner(
    writer,
    state,
):
    """
    Scan the world ONLY after Packet 49.

    This is the important difference from the
    previous version.
    """

    # --------------------------------------------------------
    # Wait for Connection Complete
    # --------------------------------------------------------

    print()
    print(
        "[*] Scanner waiting for "
        "Connection Complete..."
    )

    try:

        await asyncio.wait_for(
            state.connection_complete.wait(),
            timeout=30,
        )

    except asyncio.TimeoutError:

        print(
            "[!] Packet 49 was not received "
            "within 30 seconds."
        )

        return

    if not state.running:
        return

    # Give the server a small amount of time
    # after Packet 49.
    await asyncio.sleep(1.0)

    world = state.world_map

    if world is None:
        print(
            "[!] No world storage."
        )
        return

    columns = (
        world.section_columns
    )

    rows = (
        world.section_rows
    )

    total = (
        columns * rows
    )

    print()
    print("[*] Section grid:")

    print(
        f"    {columns} x {rows}"
    )

    print(
        f"    Total: {total}"
    )

    print()
    print(
        "[*] Starting world scan..."
    )

    move = 0

    # --------------------------------------------------------
    # Start from actual spawn
    # --------------------------------------------------------

    spawn_x = state.world_info[
        "spawn_x"
    ]

    spawn_y = state.world_info[
        "spawn_y"
    ]

    print(
        f"[>] Moving to spawn "
        f"{spawn_x},{spawn_y}"
    )

    await send_update_player(
        writer,
        state.player_id,
        spawn_x,
        spawn_y,
    )

    move += 1

    await asyncio.sleep(
        MOVE_DELAY
    )

    # --------------------------------------------------------
    # Scan sections
    # --------------------------------------------------------

    for sy in range(rows):

        if not state.running:
            break

        if sy % 2 == 0:

            x_range = range(
                columns
            )

        else:

            x_range = range(
                columns - 1,
                -1,
                -1,
            )

        for sx in x_range:

            if not state.running:
                break

            x = (
                sx
                * SECTION_WIDTH
                + SECTION_WIDTH // 2
            )

            y = (
                sy
                * SECTION_HEIGHT
                + SECTION_HEIGHT // 2
            )

            x = min(
                x,
                world.width - 1,
            )

            y = min(
                y,
                world.height - 1,
            )

            await send_update_player(
                writer,
                state.player_id,
                x,
                y,
            )

            move += 1

            print(
                f"[>] Move "
                f"{move} "
                f"-> {x},{y} "
                f"| sections="
                f"{len(world.sections)}"
            )

            await asyncio.sleep(
                MOVE_DELAY
            )

    print()
    print(
        "[+] Scan path finished."
    )


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

        self.connection_complete = (
            asyncio.Event()
        )

        self.running = True

        self.packet10_count = 0

        self.decode_errors = 0

        self.server_disconnect = False


# ============================================================
# RECEIVER
# ============================================================

async def receiver(
    reader,
    writer,
    state,
):
    """Receive server packets."""

    try:

        while state.running:

            packet_id, payload = (
                await read_packet(
                    reader
                )
            )

            # ------------------------------------------------
            # Disconnect
            # ------------------------------------------------

            if packet_id == 2:

                state.server_disconnect = True

                print()
                print(
                    "[!] Server disconnected."
                )

                # Packet 2 contains NetworkText,
                # not necessarily a simple Terraria string.
                #
                # Print raw payload too so we can identify
                # the exact reason if the server kicks us.

                print(
                    "    Payload:",
                    payload.hex(" "),
                )

                try:

                    reason, _ = read_string(
                        payload,
                        0,
                    )

                    print(
                        "    String:",
                        repr(reason),
                    )

                except Exception as exc:

                    print(
                        "    NetworkText "
                        f"decode failed: {exc}"
                    )

                state.running = False

                break

            # ------------------------------------------------
            # Set User Slot
            # ------------------------------------------------

            if packet_id == 3:

                if not payload:
                    continue

                state.player_id = (
                    payload[0]
                )

                print(
                    f"[+] Player ID: "
                    f"{state.player_id}"
                )

                # SAME ORDER AS WORKING CODE
                await send_player_info(
                    writer,
                    state.player_id,
                )

                await send_inventory(
                    writer,
                    state.player_id,
                )

                await request_world(
                    writer
                )

                continue

            # ------------------------------------------------
            # World Info
            # ------------------------------------------------

            if packet_id == 7:

                try:

                    info = parse_world_info(
                        payload
                    )

                except Exception as exc:

                    print(
                        "[!] WorldInfo parse "
                        f"error: {exc}"
                    )

                    continue

                state.world_info = info

                print()
                print(
                    "========== WORLD =========="
                )

                print(
                    f"Name:      "
                    f"{info['name']}"
                )

                print(
                    f"Size:      "
                    f"{info['width']} x "
                    f"{info['height']}"
                )

                print(
                    f"Spawn:     "
                    f"{info['spawn_x']}, "
                    f"{info['spawn_y']}"
                )

                print(
                    f"Surface:   "
                    f"{info['surface']}"
                )

                print(
                    f"Rock:      "
                    f"{info['rock_layer']}"
                )

                print(
                    f"World ID:  "
                    f"{info['world_id']}"
                )

                print(
                    f"Game Mode: "
                    f"{info['game_mode']}"
                )

                print(
                    "============================"
                )

                if not state.world_info_received:

                    state.world_info_received = True

                    state.world_map = WorldMap(
                        info["width"],
                        info["height"],
                    )

                    # SAME AS WORKING CODE:
                    # request around actual spawn.
                    await request_essential_tiles(
                        writer,
                        info["spawn_x"],
                        info["spawn_y"],
                    )

                continue

            # ------------------------------------------------
            # Packet 10
            # ------------------------------------------------

            if packet_id == 10:

                state.packet10_count += 1

                try:

                    (
                        start_x,
                        start_y,
                        width,
                        height,
                        tiles,
                    ) = parse_section(
                        payload
                    )

                    if state.world_map is None:
                        continue

                    added = (
                        state.world_map.add_section(
                            start_x,
                            start_y,
                            width,
                            height,
                            tiles,
                        )
                    )

                    if not added:
                        continue

                    number = len(
                        state.world_map.sections
                    )

                    print(
                        f"[+] Section "
                        f"{number}: "
                        f"{start_x},"
                        f"{start_y} "
                        f"{width}x"
                        f"{height}"
                    )

                    # ----------------------------------------
                    # Spawn only once.
                    # ----------------------------------------

                    if not state.spawn_sent:

                        state.spawn_sent = True

                        await send_spawn_player(
                            writer,
                            state.player_id,
                            state.world_info[
                                "spawn_x"
                            ],
                            state.world_info[
                                "spawn_y"
                            ],
                        )

                        print(
                            "[>] Spawn packet sent"
                        )

                except Exception as exc:

                    state.decode_errors += 1

                    print(
                        "[!] Packet 10 decode "
                        f"error: {exc}"
                    )

                continue

            # ------------------------------------------------
            # Connection Complete
            # ------------------------------------------------

            if packet_id == 49:

                print()
                print(
                    "[+] Connection complete"
                )

                # IMPORTANT:
                # Scanner waits for this event.
                state.connection_complete.set()

                continue

            # ------------------------------------------------
            # Other packets
            # ------------------------------------------------

            if packet_id == 9:
                continue

            if packet_id == 12:
                continue

            if packet_id == 14:
                continue

    except asyncio.IncompleteReadError:

        print(
            "[!] Connection closed by server."
        )

    except asyncio.CancelledError:

        pass

    except Exception as exc:

        print(
            "[!] Receiver error:"
        )

        print(
            f"    {type(exc).__name__}: "
            f"{exc}"
        )

    finally:

        state.running = False


# ============================================================
# MAIN
# ============================================================

async def main():
    """Main program."""

    state = State()

    print(
        "=========================================="
    )

    print(
        " Terraria 1.4.5.x World Map Downloader"
    )

    print(
        "=========================================="
    )

    print(
        f"[*] Connecting to "
        f"{HOST}:{PORT}"
    )

    try:

        reader, writer = (
            await asyncio.open_connection(
                HOST,
                PORT,
            )
        )

    except Exception as exc:

        print(
            "[!] Connection failed:"
        )

        print(
            f"    {repr(exc)}"
        )

        return

    print("[+] Connected")

    receiver_task = None
    scanner_task = None

    try:

        # ----------------------------------------------------
        # Packet 1
        #
        # THIS IS THE IMPORTANT PART.
        #
        # We use:
        #
        #     write_string("Terraria319")
        #
        # instead of:
        #
        #     b"Terraria319"
        # ----------------------------------------------------

        await send_packet(
            writer,
            1,
            write_string(
                VERSION
            ),
        )

        print(
            f"[>] Version sent: "
            f"{VERSION}"
        )

        # ----------------------------------------------------
        # Start receiver
        # ----------------------------------------------------

        receiver_task = (
            asyncio.create_task(
                receiver(
                    reader,
                    writer,
                    state,
                )
            )
        )

        # ----------------------------------------------------
        # Wait until WorldInfo exists
        # ----------------------------------------------------

        while (
            state.world_map is None
            and state.running
            and not receiver_task.done()
        ):

            await asyncio.sleep(
                0.1
            )

        if state.world_map is None:

            print(
                "[!] World was not received."
            )

            return

        # ----------------------------------------------------
        # Start scanner.
        #
        # Scanner itself waits for Packet 49.
        # ----------------------------------------------------

        if SCAN_WHOLE_WORLD:

            scanner_task = (
                asyncio.create_task(
                    scanner(
                        writer,
                        state,
                    )
                )
            )

            # Wait for scanner OR disconnect.
            while (
                not scanner_task.done()
                and state.running
            ):

                await asyncio.sleep(
                    0.2
                )

            if (
                scanner_task
                and scanner_task.done()
            ):

                try:
                    await scanner_task
                except Exception as exc:
                    print(
                        "[!] Scanner error:",
                        repr(exc),
                    )

        # ----------------------------------------------------
        # Give receiver a moment to process final sections
        # ----------------------------------------------------

        await asyncio.sleep(
            2.0
        )

    except KeyboardInterrupt:

        print(
            "\n[!] Stopped by user."
        )

    except Exception as exc:

        print()
        print(
            "[!] ERROR:"
        )

        print(
            f"    {type(exc).__name__}: "
            f"{exc}"
        )

    finally:

        state.running = False

        # ----------------------------------------------------
        # Cancel scanner
        # ----------------------------------------------------

        if scanner_task:

            if not scanner_task.done():

                scanner_task.cancel()

                try:
                    await scanner_task
                except asyncio.CancelledError:
                    pass

        # ----------------------------------------------------
        # Cancel receiver
        # ----------------------------------------------------

        if receiver_task:

            if not receiver_task.done():

                receiver_task.cancel()

                try:
                    await receiver_task
                except asyncio.CancelledError:
                    pass

        # ----------------------------------------------------
        # Results
        # ----------------------------------------------------

        print()
        print(
            "=========================================="
        )

        print("[+] RESULT")

        print(
            "=========================================="
        )

        print(
            f"Packet 10 received: "
            f"{state.packet10_count}"
        )

        print(
            f"Packet 10 errors: "
            f"{state.decode_errors}"
        )

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

            print(
                f"Sections received: "
                f"{len(world.sections)}"
            )

            print(
                f"Sections expected: "
                f"{expected}"
            )

            if len(world.sections) > 0:

                try:

                    create_png(
                        world,
                        state.world_info,
                    )

                except Exception as exc:

                    print(
                        "[!] PNG error:"
                    )

                    print(
                        f"    {type(exc).__name__}: "
                        f"{exc}"
                    )

        # ----------------------------------------------------
        # Close world storage
        # ----------------------------------------------------

        if state.world_map is not None:

            try:
                state.world_map.close()
            except Exception as exc:

                print(
                    "[!] Storage close error:",
                    repr(exc),
                )

        # ----------------------------------------------------
        # Close connection
        # ----------------------------------------------------

        try:

            writer.close()

            await writer.wait_closed()

        except Exception:

            pass

        print()
        print(
            "[*] Finished."
        )


# ============================================================
# RUN
# ============================================================

if __name__ == "__main__":
    asyncio.run(main())
