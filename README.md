# Terraria Server Map Scanner

""Python" (https://img.shields.io/badge/Python-3.8%2B-blue.svg)" (https://www.python.org/)
""Terraria" (https://img.shields.io/badge/Terraria-1.4.5.x-00AEEF.svg)" (https://terraria.org/)
["Status" (https://img.shields.io/badge/Status-Experimental-orange.svg)]
""License" (https://img.shields.io/badge/License-MIT-green.svg)" (LICENSE)

A Python-based Terraria network client that connects directly to a Terraria server, performs the initial handshake, receives world data through Terraria packets, decodes compressed tile sections, stores the world in disk-backed memory-mapped files, and renders the collected world data into a PNG map.

«Status: Experimental / Research Project
Target: Terraria 1.4.5.x protocol»

---

# ✨ Features

- 🔌 Direct TCP connection to a Terraria server
- 🤝 Terraria protocol handshake
- 👤 Automatic player slot handling
- 🌍 WorldInfo parsing
- 🧱 Terraria tile-section decoding
- 📦 Deflate/zlib decompression
- 🔁 Terraria tile RLE decoding
- 🧱 Tile and wall storage
- 💧 Water, lava, honey, and shimmer detection
- 🎨 Tile and wall paint handling
- ⚙️ Actuator and inactive-tile metadata
- 🖼️ PNG world-map rendering
- 💾 Disk-backed world storage using "mmap"
- 📊 Section and packet statistics
- 🚶 Automated world scanning
- 🌱 Starts scanning from the actual world spawn
- 🧩 Support for Terraria tile frames
- 🛡️ Basic packet and decoding error handling

---

# 🔄 How It Works

The program communicates with the Terraria server using a raw TCP connection.

The general protocol flow is:

```
TCP Connection
      │
      ▼
Packet 1 ──► Send Terraria version
      │
      ▼
Packet 3 ──► Receive player slot
      │
      ├──► Send PlayerInfo (Packet 4)
      ├──► Send Inventory (Packet 5)
      └──► Request WorldInfo (Packet 6)
                    │
                    ▼
             WorldInfo (Packet 7)
                    │
                    ├──► Create world storage
                    └──► Request initial tiles
                              │
                              ▼
                       Tile Sections (Packet 10)
                              │
                              ├──► Deflate decompression
                              ├──► Tile decoding
                              ├──► RLE expansion
                              └──► mmap storage
                                      │
                                      ▼
                              Connection Complete
                                (Packet 49)
                                      │
                                      ▼
                              Automated world scan
                                      │
                                      ▼
                              More Packet 10 data
                                      │
                                      ▼
                                  PNG renderer
```

---

# 📦 Requirements

- Python 3.8+
- Terraria 1.4.5.x-compatible server
- Network access to the Terraria server
- Pillow

# Install Dependencies

```pip install Pillow```

The script itself does not require a local Terraria client or a locally installed dedicated Terraria server.

---

# ⚙️ Configuration

Edit the configuration section at the top of the script:

```
HOST = "IP or DOMAIN"
PORT = 7777

VERSION = "Terraria319"
PLAYER_NAME = "Bot"

WORLD_DIR = Path("terraria_world")
PNG_FILE = Path("terraria_map.png")

SECTION_WIDTH = 200
SECTION_HEIGHT = 150

MOVE_DELAY = 0.35

SCAN_WHOLE_WORLD = True
```

# Server

Set "HOST" and "PORT" to the Terraria server you want to connect to:
```
HOST = "example.com"
PORT = 7777
```

# Player Name

The connection uses the configured player name:

```PLAYER_NAME = "Bot"```

# World Scan

Enable or disable automated world scanning:

```SCAN_WHOLE_WORLD = True```

When enabled, the scanner moves through the world section-by-section after the server reports connection completion.

# Movement Delay

The delay between scanner movement packets can be adjusted with:

```MOVE_DELAY = 0.35```

Higher values reduce packet frequency.

---

# 🚀 Running

Save the script, for example:

```terraria_map.py```

Run it with:

```python terraria_map.py```

Example startup:

```
==========================================
 Terraria 1.4.5.x World Map Downloader
==========================================
[*] Connecting to example.com:7777
[+] Connected
[>] Version sent: Terraria319

If the handshake succeeds, the program will receive and display world information:

========== WORLD ==========
Name:      World
Size:      8400 x 2400
Spawn:     1234, 123
Surface:   123
Rock:      123
World ID:  123456789
Game Mode: 0
============================
```

---

# 🗺️ Output

The program creates a directory containing the raw decoded world layers:
```
terraria_world/
├── tiles.bin
├── walls.bin
├── liquids.bin
├── paint.bin
├── metadata.bin
└── frames.bin
```

It also generates:

```terraria_map.png```

---

# 💾 Storage Format

The world is stored using memory-mapped files.

File| Bytes / Tile| Description
"tiles.bin"| 2| Tile ID
"walls.bin"| 2| Wall ID
"liquids.bin"| 2| Liquid amount + liquid type
"paint.bin"| 2| Tile paint + wall paint
"metadata.bin"| 1| Tile state/metadata flags
"frames.bin"| 4| Tile frame X/Y

This allows large worlds to be stored without keeping millions of Python objects in memory.

---

# 🧱 Tile Decoding

Packet 10 section data is compressed and decoded using Terraria's tile serialization format.

The decoder handles:

- Tile headers
- Extended tile IDs
- Wall IDs
- Liquid information
- Tile paint
- Wall paint
- Brick styles
- Half blocks
- Actuators
- Inactive tiles
- Invisible blocks
- Invisible walls
- Fullbright flags
- Tile frames
- Byte RLE
- UInt16 RLE

# Run-Length Encoding

RLE allows repeated tiles to be represented efficiently instead of transmitting every tile individually.

For example, a tile record with a run length can represent multiple consecutive identical tiles.

---

# 🖼️ Tile Frames

Some Terraria tiles require frame X/Y data.

The project maintains a bitset of tile IDs that require frame information:

```FRAME_IMPORTANT = (...)```

For these tiles, the decoder reads:

```
frame_x
frame_y
```

and stores the values in:

```frames.bin```

---

# 💧 Liquids

Liquid information is stored as a combined 16-bit value:

┌───────────────┬────────────────┐
│ Liquid Type   │ Liquid Amount  │
│    8 bits     │     8 bits     │
└───────────────┴────────────────┘

The renderer recognizes:

Type| Liquid
1| Water
2| Lava
3| Honey
4| Shimmer

Liquid color intensity is also affected by the received liquid amount.

---

# 🎨 Paint

The renderer includes a paint-color table and an approximation of Terraria's "MapHelper"-style paint behavior.

Supported paint behavior includes:

- Normal paint colors
- Dark paint
- Negative paint
- Basic color blending

Paint information is stored separately for tiles and walls.

---

# 🖌️ PNG Rendering

After scanning, the stored world data is rendered into a single PNG image.

The renderer processes the world in small vertical strips instead of constructing a huge intermediate pixel buffer for the entire world.

```
World Storage
     │
     ▼
16-row strip
     │
     ▼
Pixel generation
     │
     ▼
Pillow Image
     │
     ▼
PNG
```

The output resolution matches the Terraria world dimensions:

world_width × world_height

For example:

```8400 × 2400```

produces an:

```8400 × 2400 PNG```

# Background Rendering

Empty areas are approximated using the "WorldInfo" surface and rock-layer values.

The renderer distinguishes between:

- Surface / sky
- Underground
- Deeper underground

This provides a useful map background even when no active tile or wall exists at a coordinate.

---

# 🛡️ Error Handling

The project performs validation during packet and tile decoding.

Examples include:

- Invalid packet length
- Unexpected end of string
- Missing tile ID
- Missing wall ID
- Missing liquid amount
- Missing tile frame
- Invalid RLE data
- Invalid section size
- WorldInfo parse errors
- Packet 10 decoding errors

Malformed packets should therefore fail gracefully instead of silently corrupting world storage.

---

# 📡 Protocol Details

One important part of the handshake is the version packet.

The project sends the Terraria version using Terraria's 7-bit string format:
```
await send_packet(
    writer,
    1,
    write_string(VERSION),
)
```

rather than sending raw UTF-8 bytes directly.

The custom "write_string()" and "read_string()" functions implement Terraria-style 7-bit length-prefixed strings.

---

# 📋 Packet Handling

The current implementation explicitly handles several Terraria packet IDs:

Packet| Purpose
"1"| Version
"2"| Disconnect
"3"| Set User Slot
"4"| Player Info
"5"| Inventory
"6"| Request WorldInfo
"7"| WorldInfo
"8"| Request initial tiles
"9"| Tile section request / related handling
"10"| Tile section data
"12"| Spawn Player
"13"| Update Player
"14"| Player-related packet
"49"| Connection Complete

Only the packet types required by the current downloader are actively processed.

---

# 🚶 World Scanner

After receiving Packet "49" ("Connection Complete"), the scanner begins moving through the world.

The world is divided into:

```200 × 150 tiles```

sections.

The scanner uses a serpentine path:
```
→ → → → → →
← ← ← ← ← ←
→ → → → → →
← ← ← ← ← ←
```

This avoids repeatedly returning to the same side of the world.

The scanner begins at the actual spawn position received from "WorldInfo".

---

# 🧠 Memory Mapping

Large Terraria worlds can contain millions of tiles.

Instead of storing every tile as a Python dictionary permanently, the project creates fixed-size binary files and maps them into memory:

```mmap.mmap(...)```

For each world tile, the project stores compact binary information.

For example, tile IDs are stored as unsigned 16-bit values:

```
struct.pack_into(
    "<H",
    tiles_map,
    offset,
    tile["tile_id"],
)
```

This significantly reduces Python object overhead compared with keeping millions of dictionaries in memory.

---

# 📏 World Size Considerations

Storage requirements are approximately:

Layer| Size per Tile
Tiles| 2 bytes
Walls| 2 bytes
Liquids| 2 bytes
Paint| 2 bytes
Metadata| 1 byte
Frames| 4 bytes
Total| 13 bytes

For an "8400 × 2400" world:

```20,160,000 tiles```

the six binary layers require approximately:

```262 MB```

of raw storage.

Actual disk usage may vary slightly depending on filesystem allocation and file metadata.

---

# ⚠️ Limitations

This is an experimental protocol implementation and is not intended to replace the official Terraria client.

Current limitations include:

- The tile color database is only partially populated.
- Unknown tile IDs use fallback colors.
- Unknown wall IDs use fallback colors.
- PNG colors are an approximation rather than an exact Terraria map renderer.
- "MapHelper" paint behavior is approximated.
- The implementation only supports the packet structures currently required by the project.
- Full Terraria client functionality is not implemented.
- The scanner relies on server behavior and packet responses.
- Protocol compatibility may change between Terraria versions.

---

# 📁 Project Structure

The main script is organized into several components:

```
Configuration
     │
     ├── Packet utilities
     ├── Terraria string encoding
     ├── Player / handshake
     ├── WorldInfo parser
     ├── Tile decoder
     ├── Section parser
     ├── mmap world storage
     ├── World scanner
     ├── Color / paint system
     ├── PNG renderer
     └── Async TCP receiver
```

---

🔧 Dependencies

The project primarily uses the Python standard library:

- "asyncio"
- "mmap"
- "struct"
- "zlib"
- "pathlib"

External dependency:

- "Pillow" (https://pypi.org/project/Pillow/)

---

# ⚠️ Disclaimer

This project is intended for educational, research, and protocol-analysis purposes.

It implements a custom Terraria network client and should only be used with servers you are authorized to connect to and inspect.

This project is not affiliated with, endorsed by, or sponsored by Re-Logic or Terraria.

---

# 📄 License

This project is licensed under the MIT License.

See the "LICENSE" (LICENSE) file for the full license text.

---

<p align="center">
  <sub>Built for Terraria protocol research and world-data analysis.</sub>
</p>
